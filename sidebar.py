import streamlit as st


def generateSideBar():
    with st.sidebar:
        st.page_link(label="Add Record", page="pages/add.py")
        st.page_link(label="Expense Stats ", page="pages/view.py")
        st.page_link(label="Investment Stats", page="pages/invest.py")
        st.page_link(label="Expense Forecasts", page="pages/forecast.py")
        if st.button("Logout"):
            st.session_state.pop("token", None)
            st.session_state.pop("username", None)
            st.session_state.pop("name", None)
            st.session_state["authentication_status"] = False
            st.switch_page("main.py")
