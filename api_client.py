"""Thin REST client used by every Streamlit page to talk to the FastAPI
backend (backend/app/main.py) instead of hitting the database in-process.
"""

import requests
import streamlit as st

BASE_URL = "http://localhost:8000"


def _headers():
    token = st.session_state.get("token")
    return {"Authorization": f"Bearer {token}"} if token else {}


def _request(method, path, auth=True, **kwargs):
    headers = kwargs.pop("headers", {})
    if auth:
        headers.update(_headers())

    try:
        response = requests.request(method, f"{BASE_URL}{path}", headers=headers, **kwargs)
    except requests.exceptions.RequestException as exc:
        st.error(f"Could not reach the backend at {BASE_URL}: {exc}")
        return None

    if auth and response.status_code == 401:
        st.session_state.pop("token", None)
        st.session_state.pop("username", None)
        st.session_state["authentication_status"] = False
        st.error("Your session has expired. Please log in again.")
        st.switch_page("main.py")
        st.stop()

    if not response.ok:
        try:
            detail = response.json().get("detail", response.text)
        except ValueError:
            detail = response.text
        st.error(f"Backend error: {detail}")
        return None

    return response.json()


def login(username, password):
    return _request(
        "POST", "/auth/login", auth=False, json={"username": username, "password": password}
    )


def demo_login():
    return _request("POST", "/auth/demo-login", auth=False)


def register(username, email, name, password):
    return _request(
        "POST",
        "/auth/register",
        auth=False,
        json={"username": username, "email": email, "name": name, "password": password},
    )


def get_transactions():
    return _request("GET", "/transactions") or []


def add_transaction(date, description, category, amount):
    return _request(
        "POST",
        "/transactions",
        json={
            "date": str(date),
            "description": description,
            "category": category,
            "amount": amount,
        },
    )


def transcribe_voice(wav_bytes):
    return _request(
        "POST", "/voice/transcribe", files={"audio": ("audio.wav", wav_bytes, "audio/wav")}
    )


def categorize_text(text):
    return _request("POST", "/categorize", json={"text": text})


def get_forecast():
    return _request("GET", "/forecast/me")
