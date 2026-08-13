import streamlit as st

import api_client

st.set_page_config(page_title="Home", layout='centered')

if st.session_state.get('authentication_status'):
    st.switch_page("pages/view.py")

_, col2, _ = st.columns(3)

col2.image('resources/logo.jpeg')
st.divider()

st.markdown("> ### `Money Is Hard`")
st.write("We know this better than anyone")
st.markdown("That's why we built *`yafa`*")
st.markdown("A simple, efficient way of managing your finances")
st.divider()

st.markdown("#### More than 50% of India's youngsters are financially illiterate ")
st.markdown("""> Help us spread awareness about investments, savings and ultimately `Financial Freedom`. Knowledge about mutual funds, stocks and planning about financial goals make your money game unbeatable.""")
st.divider()

if st.button("🚀 Try Demo Account", use_container_width=True):
    result = api_client.demo_login()
    if result:
        st.session_state["token"] = result["access_token"]
        st.session_state["username"] = result["username"]
        st.session_state["name"] = result["name"]
        st.session_state["authentication_status"] = True
        st.toast("Logged into demo account!")
        st.switch_page("pages/view.py")
st.divider()

login_tab, register_tab = st.tabs(["Log in", "Register"])

with login_tab:
    with st.form("login_form"):
        username = st.text_input("Username")
        password = st.text_input("Password", type="password")
        submitted = st.form_submit_button("Log in")
    if submitted:
        result = api_client.login(username, password)
        if result:
            st.session_state["token"] = result["access_token"]
            st.session_state["username"] = result["username"]
            st.session_state["name"] = result["name"]
            st.session_state["authentication_status"] = True
            st.toast("Logged in!")
            st.switch_page("pages/view.py")

with register_tab:
    with st.form("register_form"):
        reg_username = st.text_input("Username", key="reg_username")
        reg_email = st.text_input("Email", key="reg_email")
        reg_name = st.text_input("Full name", key="reg_name")
        reg_password = st.text_input("Password", type="password", key="reg_password")
        reg_submitted = st.form_submit_button("Register")
    if reg_submitted:
        result = api_client.register(reg_username, reg_email, reg_name, reg_password)
        if result:
            st.success("User created successfully. Please log in.")
