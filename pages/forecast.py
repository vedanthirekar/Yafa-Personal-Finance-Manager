import matplotlib.pyplot as plt
import pandas as pd
import streamlit as st

import api_client
from sidebar import generateSideBar

st.set_page_config(page_title="Forecast", layout='centered')

if not st.session_state.get('authentication_status'):
    st.switch_page("main.py")

generateSideBar()

st.title("`Forecast` :bar_chart:")
st.divider()
st.write("This is a forecast of your future expenses. This graph also shows the seasonality within a year.")

data = api_client.get_forecast()

if not data:
    st.info("Data is not enough. Keep using `yafa` for further predictions")
    st.stop()

history = pd.DataFrame(data["history"])
forecast = pd.DataFrame(data["forecast"])
history["date"] = pd.to_datetime(history["date"])
forecast["date"] = pd.to_datetime(forecast["date"])

bridge = pd.concat([history.tail(1), forecast])

fig, ax = plt.subplots(figsize=(9, 6))
ax.plot(history["date"], history["amount"], label="Original Data", color="blue")
ax.plot(bridge["date"], bridge["amount"], color="red", label="Forecast")
ax.set_title("Monthly ARIMA Forecast")
ax.set_xlabel("Date")
ax.set_ylabel("Amount")
ax.legend()

st.pyplot(fig)

with st.expander(label="Learn more"):
    st.write("We use time series prediction to provide a rough forecasting of your expenses.")
