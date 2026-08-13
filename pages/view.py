import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import streamlit as st
from streamlit_extras.metric_cards import style_metric_cards

import api_client
from sidebar import generateSideBar

st.set_page_config(layout='wide')

if not st.session_state.get('authentication_status'):
    st.switch_page("main.py")

generateSideBar()

st.title("`Expense At a Glance` :moneybag: ")
st.divider()

records = api_client.get_transactions()
if not records:
    st.info("You don't have enough data. Keep using `yafa` for expenditure stats")
    st.stop()

df = pd.DataFrame(records)
df['date'] = pd.to_datetime(df['date'])
df = df.sort_values(by='date', ascending=False)

num_categories = df['category'].nunique()

avg = round(df['amount'].mean(), 2)
last_30 = df.head(30)['amount'].sum()
last_expense = df.iloc[0]['amount']

col1, col2, col3 = st.columns(3)
col1.metric("Average Expenditure", "Rs. " + str(avg))
col2.metric("Sum of last 30 Expenditure", "Rs. " + str(last_30))
col3.metric("Last Expenditure", "Rs. " + str(last_expense))

style_metric_cards()

st.divider()

monthly_expenses = df.groupby(df['date'].dt.to_period('M'))['amount'].sum().reset_index()
monthly_expenses['date'] = monthly_expenses['date'].dt.to_timestamp()
st.markdown("Expense by Month")
st.line_chart(data=monthly_expenses, x="date", y="amount")

st.divider()

item_prices = df.groupby('category')['amount'].sum()
total_price = item_prices.sum()
item_percentages = (item_prices / total_price) * 100
fig, ax = plt.subplots(figsize=(13, 5))
ax.pie(
    item_percentages,
    labels=item_percentages.index,
    autopct='%1.1f%%',
    startangle=90,
    radius=0.5,
    pctdistance=0.8,
    explode=[0.025] * num_categories,
)
ax.axis('equal')
st.markdown("Pie chart ")
st.pyplot(fig)

st.divider()

display_df = df[['date', 'description', 'category', 'amount']].copy()
display_df['date'] = display_df['date'].dt.date

col1, col2 = st.columns(2)
with col1:
    d = st.date_input("Filter by Date", value=None)
with col2:
    cat_options = np.append("All", display_df['category'].unique())
    cat_select = st.selectbox("Filter by category", cat_options)

if cat_select == "All" and d is None:
    st.table(display_df)
elif d is None:
    filtered = display_df[display_df['category'] == cat_select]
    st.markdown("Expense by : " + cat_select)
    st.line_chart(data=filtered, x="date", y="amount")
    st.table(filtered)
elif cat_select == "All":
    st.table(display_df[display_df['date'] == d])
else:
    filtered = display_df[(display_df['category'] == cat_select) & (display_df['date'] == d)]
    st.markdown("Expense by : " + cat_select)
    st.table(filtered)
