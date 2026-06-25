"""
Order service — fetches order details and associated line items.

Demo incidents: inc_43 (missing HTTP timeout) + inc_13 (N+1 query pattern)
Alert file:     alerts/demo_live.json
Run demo:       python demo.py

KNOWN BUGS:
  - get_orders_with_details() performs one HTTP request per order to fetch
    line items instead of batching. Under load this causes request rate spikes,
    slow response times, and connection pool exhaustion.
  - The requests.get() call has no timeout, which means a slow upstream can
    stall a thread indefinitely.

This file is intentionally left with the bugs so the AI agent can detect,
read, rewrite, and submit a fix via GitHub PR.
"""

import requests

ORDERS_API = "https://api.internal/orders"
LINE_ITEMS_API = "https://api.internal/line-items"


def get_all_orders() -> list[dict]:
    """Fetch the full list of orders from the orders microservice."""
    # BUG: no timeout — a slow API will hang this thread forever
    resp = requests.get(ORDERS_API)
    resp.raise_for_status()
    return resp.json()


def get_line_items_for_order(order_id: str) -> list[dict]:
    """Fetch line items for a single order."""
    # BUG: no timeout
    resp = requests.get(f"{LINE_ITEMS_API}?order_id={order_id}")
    resp.raise_for_status()
    return resp.json()


def get_orders_with_details() -> list[dict]:
    """
    Return all orders with their line items embedded.

    BUG — N+1 query pattern:
      For 500 orders this executes 501 HTTP requests sequentially.
      Each request has no timeout.
      Under high load this exhausts the connection pool and causes the
      checkout service to start returning 502/504 errors.
    """
    orders = get_all_orders()

    for order in orders:
        # One HTTP round-trip per order — classic N+1
        order["line_items"] = get_line_items_for_order(order["id"])

    return orders


def calculate_order_total(order: dict) -> float:
    """Sum the price * quantity for all line items in an order."""
    return sum(
        item["price"] * item["quantity"]
        for item in order.get("line_items", [])
    )
