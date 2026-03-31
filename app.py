import logging
import os
import re
import json
import importlib
from typing import Any
from datetime import datetime
from uuid import uuid4

import requests
from dotenv import load_dotenv
from flask import Flask, Response, render_template, request, session, stream_with_context

try:
    _langchain_runnables = importlib.import_module("langchain_core.runnables")
    RunnableLambda = getattr(_langchain_runnables, "RunnableLambda")
    LANGCHAIN_AVAILABLE = True
except Exception:
    RunnableLambda = None
    LANGCHAIN_AVAILABLE = False

load_dotenv()
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = Flask(__name__)
app.secret_key = os.getenv("FLASK_SECRET_KEY", os.urandom(24))

UUID_PATTERN = re.compile(
    r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}"
)
RELAXED_UUID_PATTERN = re.compile(
    r"([0-9a-fA-F]{8})[-\s]?([0-9a-fA-F]{4})[-\s]?([0-9a-fA-F]{4})[-\s]?([0-9a-fA-F]{4})[-\s]?([0-9a-fA-F]{12})"
)
MAX_SCHEDULE_RESULTS = 1
SESSION_STORE: dict[str, dict[str, Any]] = {}


class ToolboxClient:
    def __init__(self) -> None:
        configured_url = os.getenv("MCP_TOOLBOX_URL", "").strip()
        if configured_url and not configured_url.endswith("/mcp"):
            configured_url = configured_url.rstrip("/") + "/mcp"
        self.base_url = configured_url.rstrip("/")
        self.api_key = os.getenv("MCP_TOOLBOX_API_KEY", "")
        self.request_id = 1

    def is_configured(self) -> bool:
        return bool(self.base_url)

    def _headers(self) -> dict[str, str]:
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        return headers

    def _next_request_id(self) -> int:
        self.request_id += 1
        return self.request_id

    def _empty_result_message(self, tool_name: str, parameters: dict[str, Any]) -> str:
        if tool_name == "query-schedules":
            origin = parameters.get("origin", "the selected origin")
            destination = parameters.get("destination", "the selected destination")
            return (
                f"No schedules found from {origin} to {destination}. "
                "Try nearby city names or remove date words like tomorrow/today."
            )
        if tool_name == "find-bus-schedules":
            return "No schedules are currently available."
        if tool_name == "search-policies":
            return "No matching policy information was found."
        return "No results returned by the tool."

    def invoke_tool(self, tool_name: str, parameters: dict[str, Any]) -> str:
        if not self.is_configured():
            return (
                "MCP toolbox endpoint is not configured. "
                "Set MCP_TOOLBOX_URL in your environment."
            )

        payload = {
            "jsonrpc": "2.0",
            "id": self._next_request_id(),
            "method": "tools/call",
            "params": {
                "name": tool_name,
                "arguments": parameters,
            },
        }

        try:
            response = requests.post(
                self.base_url,
                json=payload,
                headers=self._headers(),
                timeout=20,
            )
            if not response.ok:
                return f"MCP toolbox returned {response.status_code}: {response.text}"

            body = response.json() if response.text else {}
            if not isinstance(body, dict):
                return str(body)

            if body.get("error"):
                return f"Tool error: {body['error']}"

            result = body.get("result", {})
            content = result.get("content", []) if isinstance(result, dict) else []
            if isinstance(content, list) and content:
                text_parts = [
                    str(part.get("text", "")).strip()
                    for part in content
                    if isinstance(part, dict) and str(part.get("text", "")).strip()
                ]
                if text_parts:
                    return "\n".join(text_parts)

            if isinstance(content, list) and not content:
                return self._empty_result_message(tool_name, parameters)

            return str(result) if result else self._empty_result_message(tool_name, parameters)
        except Exception as exc:
            return f"Unable to reach MCP toolbox. Last error: {exc}"


class McpToolboxService:
    def __init__(self, client: ToolboxClient) -> None:
        self.client = client

    def find_all_schedules(self) -> str:
        return self.client.invoke_tool("find-bus-schedules", {})

    def query_schedules(self, origin: str, destination: str) -> str:
        return self.client.invoke_tool(
            "query-schedules", {"origin": origin, "destination": destination}
        )

    def search_policies(self, search_query: str) -> str:
        return self.client.invoke_tool("search-policies", {"search_query": search_query})

    def sanitize_trip_id(self, trip_id: str) -> str:
        match = UUID_PATTERN.search(trip_id or "")
        return match.group(0) if match else ""

    def resolve_booking_id(self, raw_content: str, trip_id: str) -> str:
        uuids = UUID_PATTERN.findall(raw_content or "")
        for found in uuids:
            if found.lower() != trip_id.lower():
                return found
        return uuids[0] if uuids else f"BK-{uuid4().hex[:8]}"

    def execute_book_ticket(self, trip_id: str, passenger_name: str) -> dict[str, Any]:
        clean_trip = self.sanitize_trip_id(trip_id)
        if not clean_trip:
            return {"success": False, "message": "Trip ID must be a valid UUID.", "raw": ""}

        params_attempts = [
            ("book-ticket-ui", {"trip_id": clean_trip, "passenger_name": passenger_name}),
            ("book-ticket-ui", {"tripId": clean_trip, "passengerName": passenger_name}),
            ("book-ticket", {"trip_id": clean_trip, "passenger_name": passenger_name}),
            ("book-ticket", {"tripId": clean_trip, "passengerName": passenger_name}),
        ]

        previous_error = ""
        for tool_name, params in params_attempts:
            raw = self.client.invoke_tool(tool_name, params)
            if raw and "Tool error:" not in raw and "Unable to reach MCP toolbox" not in raw:
                if "No results returned" not in raw and "No data" not in raw:
                    return {"success": True, "message": "OK", "raw": raw, "trip_id": clean_trip}
            previous_error = f"{previous_error} | {tool_name} failed: {raw}".strip(" |")

        return {"success": False, "message": previous_error or "Booking failed.", "raw": ""}

    def book_ticket_for_ui(self, trip_id: str, passenger_name: str) -> dict[str, Any]:
        booking_result = self.execute_book_ticket(trip_id, passenger_name)
        if not booking_result["success"]:
            return {
                "success": False,
                "message": booking_result["message"],
                "bookingId": "",
                "tripId": "",
                "passengerName": "",
                "status": "",
                "bookingTime": "",
            }

        clean_trip = booking_result.get("trip_id", "")
        booking_id = self.resolve_booking_id(booking_result.get("raw", ""), clean_trip)
        return {
            "success": True,
            "message": "Ticket generated successfully.",
            "bookingId": booking_id,
            "tripId": clean_trip,
            "passengerName": passenger_name,
            "status": "CONFIRMED",
            "bookingTime": datetime.utcnow().isoformat() + "Z",
        }


toolbox_client = ToolboxClient()
mcp_service = McpToolboxService(toolbox_client)
CITY_PAIR_PATTERN = re.compile(r"from\s+([a-zA-Z\s]+)\s+to\s+([a-zA-Z\s]+)", re.IGNORECASE)
BETWEEN_PATTERN = re.compile(r"between\s+([a-zA-Z\s]+?)\s+and\s+([a-zA-Z\s]+)", re.IGNORECASE)
GREETING_PATTERN = re.compile(r"\b(hi|hello|hey)\b", re.IGNORECASE)


CITY_ALIASES = {
    "newyork": "new york",
    "nyc": "new york",
    "la": "los angeles",
    "sf": "san francisco",
}

TRAILING_TIME_WORDS = {
    "today",
    "tomorrow",
    "tonight",
    "now",
    "morning",
    "afternoon",
    "evening",
}

POLICY_KEYWORDS = (
    "policy",
    "refund",
    "baggage",
    "luggage",
    "pet",
    "pets",
    "dog",
    "dogs",
    "animal",
    "service animal",
    "cancel",
    "cancellation",
)


def normalize_city(raw_city: str) -> str:
    city = re.sub(r"\s+", " ", raw_city.strip().lower())
    words = city.split(" ")
    while words and words[-1] in TRAILING_TIME_WORDS:
        words.pop()
    city = " ".join(words).strip()
    city = CITY_ALIASES.get(city, city)
    return city.title() if city else raw_city.strip()


def parse_route_intent(text: str) -> tuple[str, str] | None:
    from_to = CITY_PAIR_PATTERN.search(text)
    if from_to:
        return normalize_city(from_to.group(1)), normalize_city(from_to.group(2))

    between = BETWEEN_PATTERN.search(text)
    if between:
        return normalize_city(between.group(1)), normalize_city(between.group(2))

    return None


def parse_json_objects(raw: str) -> list[dict[str, Any]]:
    objects: list[dict[str, Any]] = []

    for line in [ln.strip() for ln in raw.splitlines() if ln.strip()]:
        try:
            item = json.loads(line)
            if isinstance(item, dict):
                objects.append(item)
            elif isinstance(item, list):
                objects.extend([entry for entry in item if isinstance(entry, dict)])
            continue
        except Exception:
            pass

    if objects:
        return objects

    # Fallback for concatenated payloads like {...}{...}
    for match in re.findall(r"\{[^{}]*\}", raw):
        try:
            item = json.loads(match)
            if isinstance(item, dict):
                objects.append(item)
        except Exception:
            continue

    return objects


def format_schedule_response(raw: str, origin_hint: str = "", destination_hint: str = "") -> str:
    entries = parse_json_objects(raw)
    formatted: list[str] = []

    def build_line(item: dict[str, Any]) -> str:
        trip_id = str(item.get("trip_id", "-")).strip()
        departure = str(item.get("departure_time", "-")).strip()
        arrival = str(item.get("arrival_time", "-")).strip()
        seats = str(item.get("available_seats", "-")).strip()
        origin = str(item.get("origin_city", "")).strip() or origin_hint
        destination = str(item.get("destination_city", "")).strip() or destination_hint
        price_value = item.get("ticket_price", "-")
        try:
            price = f"{float(price_value):.2f}"
        except Exception:
            price = str(price_value).strip()

        route_line = f"Route: {origin} -> {destination}\n" if origin and destination else ""

        return (
            f"Trip ID: {trip_id}\n"
            f"{route_line}"
            f"Departure: {departure}\n"
            f"Arrival: {arrival}\n"
            f"Price: ${price}\n"
            f"Seats: {seats}"
        )

    for item in entries[:MAX_SCHEDULE_RESULTS]:
        if "trip_id" in item:
            formatted.append(build_line(item))

    if formatted:
        return "\n\n".join(formatted)

    # Fallback for already formatted strings that got concatenated without newlines.
    if "Trip ID:" in raw:
        chunks = [chunk.strip() for chunk in raw.split("Trip ID:") if chunk.strip()]
        rebuilt = [f"Trip ID: {chunk}" for chunk in chunks[:MAX_SCHEDULE_RESULTS]]
        return "\n".join(rebuilt)

    return raw


def format_policy_response(raw: str) -> str:
    entries = parse_json_objects(raw)
    seen: set[str] = set()
    lines: list[str] = []

    for item in entries:
        category = str(item.get("category", "Policy")).strip() or "Policy"
        policy_text = str(item.get("policy_text", "")).strip()
        if not policy_text:
            continue
        key = f"{category}|{policy_text}"
        if key in seen:
            continue
        seen.add(key)
        lines.append(f"- {category}: {policy_text}")

    if lines:
        return "\n".join(lines)
    return raw


def get_state(session_id: str) -> dict[str, Any]:
    if session_id not in SESSION_STORE:
        SESSION_STORE[session_id] = {
            "initialized": False,
            "cached_schedules": "",
            "pending_trip_id": "",
            "last_schedule_lines": [],
            "awaiting_booking_name": False,
            "last_origin": "",
            "last_destination": "",
        }
    return SESSION_STORE[session_id]


def bootstrap_schedules(session_id: str) -> str:
    state = get_state(session_id)
    if state["initialized"]:
        return state["cached_schedules"]
    broad = mcp_service.find_all_schedules()
    state["initialized"] = True
    state["cached_schedules"] = broad
    return broad


def extract_trip_id(text: str) -> str:
    match = UUID_PATTERN.search(text or "")
    if match:
        return match.group(0)

    relaxed = RELAXED_UUID_PATTERN.search(text or "")
    if not relaxed:
        return ""

    return "-".join(relaxed.groups())


def parse_name_after_keyword(text: str) -> str:
    match = re.search(r"\bname\s*[:\-]?\s*([A-Za-z][A-Za-z\s.'-]{1,60})", text, re.IGNORECASE)
    if not match:
        return ""

    value = re.sub(r"\s+", " ", match.group(1)).strip(" .,-")
    if not re.fullmatch(r"[A-Za-z][A-Za-z\s.'-]{1,60}", value):
        return ""
    return value


def parse_trip_blocks(raw_schedules: str) -> list[dict[str, str]]:
    blocks: list[dict[str, str]] = []
    if not raw_schedules or "Trip ID:" not in raw_schedules:
        return blocks

    chunks = [chunk.strip() for chunk in raw_schedules.split("Trip ID:") if chunk.strip()]
    for chunk in chunks:
        block_lines = [line.strip() for line in chunk.splitlines() if line.strip()]
        if not block_lines:
            continue

        trip_id = extract_trip_id(block_lines[0])
        details = {
            "trip_id": trip_id,
            "departure": "",
            "arrival": "",
            "price": "",
            "seats": "",
            "origin": "",
            "destination": "",
        }

        for line in block_lines[1:]:
            if line.lower().startswith("route:"):
                route_text = line.split(":", 1)[1].strip()
                if "->" in route_text:
                    parts = [p.strip() for p in route_text.split("->", 1)]
                    if len(parts) == 2:
                        details["origin"], details["destination"] = parts
            elif line.lower().startswith("departure:"):
                details["departure"] = line.split(":", 1)[1].strip()
            elif line.lower().startswith("arrival:"):
                details["arrival"] = line.split(":", 1)[1].strip()
            elif line.lower().startswith("price:") or line.lower().startswith("fare:"):
                details["price"] = line.split(":", 1)[1].strip().lstrip("$")
            elif line.lower().startswith("seats:"):
                details["seats"] = line.split(":", 1)[1].strip()

        if details["trip_id"]:
            blocks.append(details)

    return blocks


def build_ticket_confirmation(ticket: dict[str, str], details: dict[str, str], state: dict[str, Any]) -> str:
    route_text = ""
    if details.get("origin") and details.get("destination"):
        route_text = f"Route: {details['origin']} -> {details['destination']}\n"
    elif state.get("last_origin") and state.get("last_destination"):
        route_text = f"Route: {state['last_origin']} -> {state['last_destination']}\n"

    trip_meta = ""
    if details.get("departure"):
        trip_meta += f"Departure: {details['departure']}\n"
    if details.get("arrival"):
        trip_meta += f"Arrival: {details['arrival']}\n"
    if details.get("price"):
        trip_meta += f"Fare: ${details['price']}\n"

    return (
        f"TICKET_CONFIRMED\n"
        f"Trip ID: {ticket['tripId']}\n"
        f"Passenger: {ticket['passengerName']}\n"
        f"{route_text}"
        f"{trip_meta}"
        f"Booking ID: {ticket['bookingId']}\n"
        f"Status: {ticket['status']}\n"
        f"Issued At: {ticket['bookingTime']}"
    )


def is_booking_intent(lowered: str) -> bool:
    return (
        ("book" in lowered and "ticket" in lowered)
        or "confirm booking" in lowered
        or "book this" in lowered
    )


def is_seat_intent(lowered: str) -> bool:
    return "seat" in lowered and ("how many" in lowered or "available" in lowered or "avail" in lowered)


def is_policy_intent(lowered: str) -> bool:
    return any(keyword in lowered for keyword in POLICY_KEYWORDS)


def build_langchain_intent_chain():
    if not LANGCHAIN_AVAILABLE or RunnableLambda is None:
        return None

    def extract_intents(text: str) -> dict[str, Any]:
        lowered = text.lower()
        return {
            "lowered": lowered,
            "is_greeting": bool(GREETING_PATTERN.search(text)) and len(lowered) <= 30,
            "route_pair": parse_route_intent(text),
            "trip_id": extract_trip_id(text),
            "passenger_name": parse_name_after_keyword(text),
            "is_booking_intent": is_booking_intent(lowered),
            "is_seat_intent": is_seat_intent(lowered),
        }

    # LangChain LCEL pipeline used for deterministic message understanding.
    return RunnableLambda(extract_intents)


LANGCHAIN_INTENT_CHAIN = build_langchain_intent_chain()


def parse_intents(text: str) -> dict[str, Any]:
    lowered = text.lower()
    fallback = {
        "lowered": lowered,
        "is_greeting": bool(GREETING_PATTERN.search(text)) and len(lowered) <= 30,
        "route_pair": parse_route_intent(text),
        "trip_id": extract_trip_id(text),
        "passenger_name": parse_name_after_keyword(text),
        "is_booking_intent": is_booking_intent(lowered),
        "is_seat_intent": is_seat_intent(lowered),
    }

    if LANGCHAIN_INTENT_CHAIN is None:
        return fallback

    try:
        parsed = LANGCHAIN_INTENT_CHAIN.invoke(text)
        if isinstance(parsed, dict):
            fallback.update(parsed)
    except Exception as exc:
        logger.debug("LangChain intent parsing failed, using fallback: %s", exc)

    return fallback


def find_seats_for_trip(trip_id: str, raw_schedules: str) -> str:
    normalized_trip_id = extract_trip_id(trip_id) or trip_id

    for item in parse_json_objects(raw_schedules):
        if isinstance(item, dict) and str(item.get("trip_id", "")).lower() == normalized_trip_id.lower():
            return str(item.get("available_seats", "unknown"))

    for block in parse_trip_blocks(raw_schedules):
        if block.get("trip_id", "").lower() == normalized_trip_id.lower():
            return block.get("seats", "unknown") or "unknown"

    return "unknown"


def find_trip_details(trip_id: str, raw_schedules: str) -> dict[str, str]:
    normalized_trip_id = extract_trip_id(trip_id) or trip_id

    for item in parse_json_objects(raw_schedules):
        if str(item.get("trip_id", "")).lower() == normalized_trip_id.lower():
            return {
                "departure": str(item.get("departure_time", "")).strip(),
                "arrival": str(item.get("arrival_time", "")).strip(),
                "price": str(item.get("ticket_price", "")).strip(),
                "seats": str(item.get("available_seats", "")).strip(),
                "origin": str(item.get("origin_city", "")).strip(),
                "destination": str(item.get("destination_city", "")).strip(),
            }

    for block in parse_trip_blocks(raw_schedules):
        if block.get("trip_id", "").lower() == normalized_trip_id.lower():
            return {
                "departure": block.get("departure", ""),
                "arrival": block.get("arrival", ""),
                "price": block.get("price", ""),
                "seats": block.get("seats", ""),
                "origin": block.get("origin", ""),
                "destination": block.get("destination", ""),
            }

    return {
        "departure": "",
        "arrival": "",
        "price": "",
        "seats": "",
        "origin": "",
        "destination": "",
    }


def serialize_json_lines(entries: list[dict[str, Any]]) -> str:
    return "\n".join(json.dumps(entry) for entry in entries)


def decrement_seats_in_cache(state: dict[str, Any], trip_id: str) -> None:
    raw = state.get("cached_schedules", "")
    entries = parse_json_objects(raw)
    changed = False
    for entry in entries:
        if str(entry.get("trip_id", "")).lower() == trip_id.lower():
            seats_value = entry.get("available_seats", 0)
            try:
                seats = int(seats_value)
            except Exception:
                seats = 0
            if seats > 0:
                entry["available_seats"] = seats - 1
                changed = True
    if changed:
        state["cached_schedules"] = serialize_json_lines(entries)


def refresh_route_cache(state: dict[str, Any]) -> None:
    origin = state.get("last_origin", "")
    destination = state.get("last_destination", "")
    if not origin or not destination:
        return
    fresh = mcp_service.query_schedules(origin, destination)
    if fresh:
        state["cached_schedules"] = fresh


def route_message(session_id: str, user_message: str) -> str:
    text = user_message.strip()

    if not text:
        return "Please enter a message."

    intent = parse_intents(text)
    lowered = str(intent.get("lowered", text.lower()))

    state = get_state(session_id)
    bootstrap_schedules(session_id)

    if bool(intent.get("is_greeting")):
        return (
            "Hello! I've fetched the broad bus schedules and I'm ready to help with your transit needs. "
            "How can I assist you today?"
        )

    route_pair = intent.get("route_pair")
    if route_pair:
        origin, destination = route_pair
        raw = mcp_service.query_schedules(origin, destination)
        state["cached_schedules"] = raw
        formatted = format_schedule_response(raw, origin, destination)
        state["last_schedule_lines"] = [line for line in formatted.splitlines() if line.strip()]
        if state["last_schedule_lines"]:
            first_trip = extract_trip_id(state["last_schedule_lines"][0])
            state["pending_trip_id"] = first_trip
            state["last_origin"] = origin
            state["last_destination"] = destination
        return formatted

    if "all" in lowered and "schedule" in lowered:
        raw = mcp_service.find_all_schedules()
        formatted = format_schedule_response(raw)
        state["cached_schedules"] = raw
        return formatted

    if "between" in lowered and "and" in lowered and ("route" in lowered or "schedule" in lowered or "bus" in lowered):
        return "Please ask in this format: from Boston to New York (or between Boston and New York)."

    if is_policy_intent(lowered):
        raw = mcp_service.search_policies(text)
        return format_policy_response(raw)

    trip_id = str(intent.get("trip_id", "") or "")
    inline_passenger_name = str(intent.get("passenger_name", "") or "")
    booking_intent = bool(intent.get("is_booking_intent"))
    seat_intent = bool(intent.get("is_seat_intent"))

    if booking_intent and trip_id and inline_passenger_name:
        state["pending_trip_id"] = trip_id
        ticket = mcp_service.book_ticket_for_ui(trip_id, inline_passenger_name)
        if not ticket["success"]:
            return f"Booking failed: {ticket['message']}"
        state["awaiting_booking_name"] = False
        decrement_seats_in_cache(state, ticket["tripId"])
        details = find_trip_details(ticket["tripId"], state.get("cached_schedules", ""))
        return build_ticket_confirmation(ticket, details, state)

    if seat_intent:
        target_trip_id = trip_id or state.get("pending_trip_id", "")
        if not target_trip_id:
            return "Please provide the Trip ID to check seat availability."
        refresh_route_cache(state)
        seats = find_seats_for_trip(target_trip_id, state.get("cached_schedules", ""))
        return f"There are {seats} seats available for Trip ID: {target_trip_id}."

    if booking_intent:
        if trip_id:
            state["pending_trip_id"] = trip_id
            state["awaiting_booking_name"] = True
            return (
                "Please share your full name to proceed with booking for Trip ID: "
                f"{trip_id}"
            )
        if state.get("pending_trip_id"):
            state["awaiting_booking_name"] = True
            return (
                "Please share your full name to proceed with booking for Trip ID: "
                f"{state['pending_trip_id']}"
            )
        return "Please provide the Trip ID you want to book."

    passenger_name = inline_passenger_name
    if (
        not passenger_name
        and state.get("pending_trip_id")
        and state.get("awaiting_booking_name")
        and len(text.split()) <= 5
    ):
        passenger_name = text.strip()

    if passenger_name and state.get("pending_trip_id"):
        ticket = mcp_service.book_ticket_for_ui(state["pending_trip_id"], passenger_name)
        if not ticket["success"]:
            return f"Booking failed: {ticket['message']}"
        state["awaiting_booking_name"] = False
        decrement_seats_in_cache(state, ticket["tripId"])
        details = find_trip_details(ticket["tripId"], state.get("cached_schedules", ""))
        return build_ticket_confirmation(ticket, details, state)

    return (
        "I can help with bus schedules, bookings, and policy queries. "
        "Try: from Boston to New York tomorrow"
    )


def sse_stream(message: str):
    lines = [line.rstrip() for line in message.splitlines() if line.strip()]
    if not lines:
        yield f"data: {message}\n\n"
        return

    for line in lines:
        yield f"data: {line}\n\n"


@app.route("/")
def index():
    session["session_id"] = os.urandom(24).hex()
    return render_template("index.html")


@app.route("/health", methods=["GET"])
def health():
    return {
        "status": "ok",
        "toolboxConfigured": toolbox_client.is_configured(),
        "langchainIntentEnabled": LANGCHAIN_INTENT_CHAIN is not None,
    }, 200


@app.route("/chat", methods=["POST"])
def chat():
    data = request.get_json(silent=True) or {}
    user_message = str(data.get("message", "")).strip()
    if not user_message:
        return "No message provided.", 400

    session_id = session.get("session_id") or os.urandom(24).hex()
    session["session_id"] = session_id

    try:
        reply = route_message(session_id, user_message)
    except Exception as exc:
        logger.exception("Chat handling failed")
        reply = f"An error occurred while processing your request: {exc}"

    return Response(
        stream_with_context(sse_stream(reply)),
        mimetype="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@app.route("/api/agent/chat", methods=["POST"])
def agent_chat():
    user_message = request.get_data(as_text=True) or ""
    session_id = session.get("session_id") or os.urandom(24).hex()
    session["session_id"] = session_id
    return route_message(session_id, user_message.strip()), 200


def stream_agent_tokens(message: str):
    parts = [part for part in message.split(" ") if part]
    for idx, part in enumerate(parts):
        suffix = "" if idx == len(parts) - 1 else " "
        yield f"event: token\ndata: {part}{suffix}\n\n"
    yield "event: final\ndata: DONE\n\n"


@app.route("/api/agent/chat/stream", methods=["POST"])
def agent_chat_stream():
    user_message = request.get_data(as_text=True) or ""
    session_id = session.get("session_id") or os.urandom(24).hex()
    session["session_id"] = session_id
    try:
        reply = route_message(session_id, user_message.strip())
    except Exception as exc:
        logger.exception("Streaming chat failed")
        reply = f"Assistant error: {exc}"

    return Response(
        stream_with_context(stream_agent_tokens(reply)),
        mimetype="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@app.route("/api/agent/book", methods=["POST"])
@app.route("/api/book", methods=["POST"])
def book_ticket():
    data = request.get_json(silent=True) or {}
    trip_id = str(data.get("tripId", "")).strip()
    passenger_name = str(data.get("passengerName", "")).strip()
    if not trip_id or not passenger_name:
        return {
            "success": False,
            "message": "Trip ID and passenger name are required.",
            "bookingId": "",
            "tripId": "",
            "passengerName": "",
            "status": "",
            "bookingTime": "",
        }, 400

    ticket = mcp_service.book_ticket_for_ui(trip_id, passenger_name)
    status = 200 if ticket.get("success") else 200
    return ticket, status


if __name__ == "__main__":
    port = int(os.getenv("PORT", "8080"))
    app.run(host="0.0.0.0", port=port, debug=False)
