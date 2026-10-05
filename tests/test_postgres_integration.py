"""End-to-end contract coverage against an actual PostgreSQL database."""
from __future__ import annotations

from uuid import uuid4


def _register_and_login(client, email: str) -> dict[str, str]:
    password = "correct-horse-battery-staple"
    registered = client.post("/auth/register", json={"email": email, "password": password})
    assert registered.status_code == 201, registered.get_json()
    login = client.post("/auth/login", json={"email": email, "password": password})
    assert login.status_code == 200, login.get_json()
    return {"Authorization": "Bearer " + login.get_json()["accessToken"]}


def _event(client, headers, *, capacity=3, budget="100.00") -> str:
    response = client.post("/events", headers=headers, json={
        "name": "Postgres Integration Event", "description": "live persistence",
        "startAt": "2030-01-10T09:00:00+00:00", "endAt": "2030-01-10T18:00:00+00:00",
        "capacity": capacity, "plannedBudget": budget,
    })
    assert response.status_code == 201, response.get_json()
    return response.get_json()["id"]


def _assert_error(response, status: int):
    assert response.status_code == status, response.get_json()
    payload = response.get_json()
    assert {"timestamp", "status", "error", "message", "path"} <= set(payload)
    assert payload["status"] == status


def test_auth_validation_public_docs_and_ownership_contract(client):
    # Documentation/spec remain accessible before login, while resource routes do not.
    assert client.get("/docs").status_code == 200
    spec = client.get("/openapi.json")
    assert spec.status_code == 200
    assert "/events/{event_id}/tasks" in spec.get_json()["paths"]
    _assert_error(client.get("/events"), 401)
    _assert_error(client.post("/auth/register", json={"email": "not-an-email", "password": "short"}), 400)

    owner = _register_and_login(client, "owner@example.test")
    other = _register_and_login(client, "other@example.test")
    event_id = _event(client, owner)
    _assert_error(client.post("/events", headers=owner, json={"name": "bad"}), 400)
    _assert_error(client.get(f"/events/{event_id}", headers=other), 403)
    _assert_error(client.get(f"/events/{uuid4()}", headers=owner), 404)


def test_guests_enforce_capacity_and_preserve_404_before_foreign_403(client):
    owner = _register_and_login(client, "guests-owner@example.test")
    stranger = _register_and_login(client, "guests-stranger@example.test")
    event_id = _event(client, owner, capacity=1)
    path = f"/events/{event_id}/guests"
    first = client.post(path, headers=owner, json={"name": "One", "email": "one@example.test", "status": "accepted"})
    assert first.status_code == 201, first.get_json()
    _assert_error(client.post(path, headers=owner, json={"name": "Two", "email": "two@example.test", "status": "accepted"}), 409)
    _assert_error(client.post(path, headers=owner, json={"name": "Bad", "email": "not-email"}), 400)
    _assert_error(client.get(path, headers=stranger), 403)
    _assert_error(client.get(f"/events/{uuid4()}/guests", headers=owner), 404)


def test_tasks_dependencies_transitions_and_audit_records(client):
    headers = _register_and_login(client, "tasks@example.test")
    event_id = _event(client, headers)
    base = f"/events/{event_id}/tasks"
    prerequisite = client.post(base, headers=headers, json={"title": "Prerequisite", "priority": "high"})
    assert prerequisite.status_code == 201, prerequisite.get_json()
    prerequisite_id = prerequisite.get_json()["id"]
    dependent = client.post(base, headers=headers, json={"title": "Dependent", "dependency_task_id": prerequisite_id})
    assert dependent.status_code == 201, dependent.get_json()
    dependent_id = dependent.get_json()["id"]
    _assert_error(client.patch(f"{base}/{dependent_id}", headers=headers, json={"status": "completed"}), 409)
    done = client.patch(f"{base}/{prerequisite_id}", headers=headers, json={"status": "completed"})
    assert done.status_code == 200
    assert client.patch(f"{base}/{dependent_id}", headers=headers, json={"status": "completed"}).status_code == 200
    _assert_error(client.patch(f"{base}/{prerequisite_id}", headers=headers, json={"dependency_task_id": prerequisite_id}), 400)

    audits = client.get(f"/events/{event_id}/audit-logs?resourceType=task", headers=headers)
    assert audits.status_code == 200, audits.get_json()
    actions = {entry["action"] for entry in audits.get_json()["items"]}
    assert {"create", "status_change"} <= actions


def test_budget_cap_exact_aggregates_and_threshold_notification(client):
    headers = _register_and_login(client, "budget@example.test")
    event_id = _event(client, headers, budget="100.00")
    categories = f"/events/{event_id}/budget-categories"
    category = client.post(categories, headers=headers, json={"name": "Food", "plannedAmount": "20.00"})
    assert category.status_code == 201, category.get_json()
    category_id = category.get_json()["id"]
    _assert_error(client.post(categories, headers=headers, json={"name": "Too much", "plannedAmount": "80.01"}), 409)
    expenses = f"{categories}/{category_id}/expenses"
    assert client.post(expenses, headers=headers, json={"name": "A", "amount": "10.10", "incurredOn": "2030-01-01"}).status_code == 201
    assert client.post(expenses, headers=headers, json={"name": "B", "amount": "9.05", "incurredOn": "2030-01-02"}).status_code == 201
    aggregate = client.get(f"/events/{event_id}/budget", headers=headers)
    assert aggregate.status_code == 200
    assert aggregate.get_json() == {"planned": "100.00", "actual": "19.15", "remaining": "80.85"}
    listed = client.get(categories, headers=headers).get_json()["items"][0]
    assert listed["actualAmount"] == "19.15"
    assert listed["remainingAmount"] == "0.85"
    notices = client.get(f"/events/{event_id}/notifications?kind=budget_threshold", headers=headers)
    assert notices.status_code == 200
    assert notices.get_json()["total"] == 1


def test_schedule_half_open_overlap_and_vendor_payment_cap(client):
    headers = _register_and_login(client, "schedule-vendor@example.test")
    event_id = _event(client, headers)
    schedule = f"/events/{event_id}/schedule-items"
    first = client.post(schedule, headers=headers, json={
        "name": "Opening", "start_at": "2030-01-10T10:00:00+00:00", "end_at": "2030-01-10T11:00:00+00:00"})
    assert first.status_code == 201, first.get_json()
    assert client.post(schedule, headers=headers, json={
        "name": "Touching", "start_at": "2030-01-10T11:00:00+00:00", "end_at": "2030-01-10T12:00:00+00:00"}).status_code == 201
    _assert_error(client.post(schedule, headers=headers, json={
        "name": "Overlap", "start_at": "2030-01-10T10:30:00+00:00", "end_at": "2030-01-10T11:30:00+00:00"}), 409)

    vendors = f"/events/{event_id}/vendors"
    vendor = client.post(vendors, headers=headers, json={"name": "Venue", "contract_amount": "10.00"})
    assert vendor.status_code == 201, vendor.get_json()
    vendor_id = vendor.get_json()["id"]
    payments = f"{vendors}/{vendor_id}/payments"
    paid = client.post(payments, headers=headers, json={"amount": "6.00", "payment_date": "2030-01-01"})
    assert paid.status_code == 201, paid.get_json()
    _assert_error(client.post(payments, headers=headers, json={"amount": "4.01", "payment_date": "2030-01-02"}), 409)
    vendor_read = client.get(f"{vendors}/{vendor_id}", headers=headers)
    assert vendor_read.status_code == 200
    assert vendor_read.get_json()["totalPaid"] == "6.00"
    assert vendor_read.get_json()["outstanding"] == "4.00"


def test_notification_scanner_is_deduplicated_against_live_postgres(client):
    headers = _register_and_login(client, "scanner@example.test")
    event_id = _event(client, headers)
    task = client.post(f"/events/{event_id}/tasks", headers=headers, json={
        "title": "Overdue task", "due_at": "2000-01-01T00:00:00+00:00"})
    assert task.status_code == 201, task.get_json()
    scanner = client.application.extensions["services"]["notifications"]
    assert scanner.scan_due_conditions() == 1
    assert scanner.scan_due_conditions() == 0
    notifications = client.get(f"/events/{event_id}/notifications?kind=task_overdue", headers=headers)
    assert notifications.status_code == 200
    assert notifications.get_json()["total"] == 1
