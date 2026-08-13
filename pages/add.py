import io
from datetime import datetime

import streamlit as st
from audiorecorder import audiorecorder

import api_client
from sidebar import generateSideBar

st.set_page_config(page_title="Add Expense", layout="centered")

categories = [
    'Education', 'Social Life', 'Transportation', 'Food',
    'Household', 'Money transfer', 'Investment', 'Tourism', 'Health', 'Subscription'
]

if not st.session_state.get('authentication_status'):
    st.switch_page("main.py")

generateSideBar()

st.title("`Add a Expense` :coin:")
st.divider()
st.write("Record a voicenote to track an expense.")


def _category_index(predicted_category):
    return categories.index(predicted_category) if predicted_category in categories else 0


def _add_expense(description, amount, category):
    if amount is None:
        st.error("Amount not detected. Please add it manually before saving.")
        return
    response = api_client.add_transaction(
        date=datetime.now().date(),
        description=description,
        category=category,
        amount=amount,
    )
    if response:
        st.success("Successfully added to the database! Use the other tabs to explore more about your financial spending.")


audio = audiorecorder("🎤", "⏺")

if len(audio) > 0:
    buffer = io.BytesIO()
    audio.export(buffer, format="wav")

    with st.spinner("Transcribing and categorizing..."):
        result = api_client.transcribe_voice(buffer.getvalue())

    if not result or not result.get("transcript"):
        st.error("Nothing got recorded!")
        st.stop()

    st.info("Given below is the text that got recorded")
    st.code(result["transcript"])

    description = result["description"]
    amount = result["amount"]
    predicted_category = result["category"]

    if predicted_category is not None:
        st.success(f"A category has been automatically detected! (confidence: {result['confidence']:.0%})")
    else:
        st.warning("Couldn't detect a category. Please select manually")

    category = st.selectbox(
        label="Category", options=categories, index=_category_index(predicted_category)
    )

    st.info("Given below are the essential components of your note.")
    st.write(f"- Description: `{description}`")
    st.write(f"- Amount: `{amount}`")

    st.button(
        "Add to database ?",
        on_click=_add_expense,
        args=(description, amount, category),
    )

with st.expander("Or type it instead (no microphone needed)"):
    manual_text = st.text_input("What did you spend on?", key="manual_description")
    manual_amount = st.number_input("Amount", min_value=0.0, step=1.0, key="manual_amount")

    if st.button("Detect category", key="manual_detect"):
        if manual_text:
            detected = api_client.categorize_text(manual_text)
            if detected:
                st.session_state["manual_category"] = detected["category"] or categories[0]
                st.info(
                    f"Detected category: `{detected['category'] or 'Uncategorized'}` "
                    f"(confidence: {detected['confidence']:.0%})"
                )

    manual_category = st.selectbox(
        label="Category",
        options=categories,
        index=_category_index(st.session_state.get("manual_category")),
        key="manual_category_select",
    )

    st.button(
        "Add to database",
        key="manual_add",
        on_click=_add_expense,
        args=(manual_text, manual_amount, manual_category),
    )

with st.expander("How does it work ?"):
    st.write("1) Record transactions using your voice (or type them manually).")
    st.write("2) Automagically detect the description, amount and category.")
    st.write("3) Add any expense with 3 taps.")
