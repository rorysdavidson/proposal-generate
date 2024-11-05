# Import Packages
import streamlit as st
from openai import AzureOpenAI
import snowflake.connector
import pandas as pd
import requests
from msal import ConfidentialClientApplication

# Streamlit Configuration and Logo Display
logo_path = "images/Logos_White.png"
st.set_page_config(layout="wide")
st.image(logo_path, width=600) 

# Configure OpenAI Client
api_key = st.secrets["OPENAI_API_KEY"]
api_version = st.secrets["OPENAI_API_VERSION"]
azure_endpoint = st.secrets["OPENAI_API_ENDPOINT"]

client = AzureOpenAI(
    api_key=api_key,
    api_version=api_version,
    azure_endpoint=azure_endpoint,
)

# Configure MSAL Authentication (Unchanged)
client_id = st.secrets["CLIENT_ID"]
client_secret = st.secrets["CLIENT_SECRET"]
tenant_id = st.secrets["TENANT_ID"]
authority = f"https://login.microsoftonline.com/{tenant_id}"
redirect_uri = "https://proposal-generate.streamlit.app/" #Prod
#redirect_uri = "http://localhost:8504/"  # Dev

app = ConfidentialClientApplication(client_id, authority=authority, client_credential=client_secret)

def get_auth_url():
    return app.get_authorization_request_url(["User.Read"], redirect_uri=redirect_uri)

def get_token_from_code(code):
    return app.acquire_token_by_authorization_code(code, scopes=["User.Read"], redirect_uri=redirect_uri)

def get_user_info(token):
    headers = {'Authorization': f"Bearer {token['access_token']}"}
    response = requests.get('https://graph.microsoft.com/v1.0/me', headers=headers)
    user_info = response.json()
    user_email = user_info.get("mail", user_info.get("userPrincipalName", ""))
    st.session_state['user_id'] = user_email
    return user_email

# Configure Snowflake Connection (Unchanged)
user = st.secrets["SNOWFLAKE_USER"]
password = st.secrets["SNOWFLAKE_PASSWORD"]
account = st.secrets["SNOWFLAKE_ACCOUNT"]
warehouse = st.secrets["SNOWFLAKE_WAREHOUSE"]
database = st.secrets["SNOWFLAKE_DATABASE"]
schema = st.secrets["SNOWFLAKE_SCHEMA"]

# Snowflake connection 
conn = snowflake.connector.connect(
    user=user,
    password=password,
    account=account,
    warehouse=warehouse,
    database=database,
    schema=schema
)

# System Message for OpenAI (Unchanged)
SYSTEM_MESSAGE =  """
You are an experienced proposal writer for Decision Inc, tasked with generating professional, comprehensive, and persuasive proposal documentation for clients.
Your goal is to create an in-depth proposal based on the provided context, tailored specifically to the client's needs.
Ensure coherence, professionalism, and persuasive language throughout the proposal.
Avoid unnecessary content like company letterheads, greetings, signatures, or repetitive information.
Write in a professional and formal tone suitable for a high-stakes project proposal from a leading data consultancy to an important client.
Your writing should be detailed, insightful, and demonstrate a deep understanding of the client's challenges and how our solutions can address them.
"""

# Function to process data into a dictionary (Unchanged)
def process_data(rows):
    data = {}
    for row in rows:
        client_name, project = row
        if client_name in data:
            data[client_name].append(project)
        else:
            data[client_name] = [project]
    return data

# Function to build prompts (Unchanged)
def build_prompt_part1(prompt_data, sections, section_overviews):
    # Concisely format the prompt data
    prompt_data_text = f"""
Client Name: {prompt_data['Client_Name']}
Project Name: {prompt_data['Project_Name']}
Solution: {prompt_data['Solution']}
Key Challenges - High Importance: {prompt_data['Key_challenges_high']}
Key Challenges - Medium Importance: {prompt_data['Key_challenges_medium']}
Key Challenges - Low Importance: {prompt_data['Key_challenges_low']}
Solution Aspects: {prompt_data['Solution_aspect']}
Additional Information: {prompt_data['Additional_info']}
"""

    # Build the instructions for the first set of sections
    sections_text = ""
    for section in sections:
        sections_text += f"### {section}\n{section_overviews[section]}\n\n"

    # Build the full prompt for part 1
    full_prompt = f"""
Use the following client information to inform your writing:
{prompt_data_text}

Please generate a comprehensive, detailed, and in-depth proposal with the following sections:

{sections_text}

Each section should be extensive and provide substantial information, insights, and analysis. Use professional language, and ensure the proposal is coherent and flows logically from one section to the next. Include relevant examples, data, and references where appropriate to support the content.
"""
    return full_prompt

def build_prompt_part2(prompt_data, previous_content, sections, section_overviews):
    # Build the instructions for the remaining sections
    sections_text = ""
    for section in sections:
        sections_text += f"### {section}\n{section_overviews[section]}\n\n"

    # Build the full prompt for part 2
    full_prompt = f"""
{SYSTEM_MESSAGE}

Use the following client information to inform your writing:
Client Name: {prompt_data['Client_Name']}
Project Name: {prompt_data['Project_Name']}
Solution: {prompt_data['Solution']}
Solution Aspects: {prompt_data['Solution_aspect']}

Previously generated content:
{previous_content}

Please continue generating the proposal with the following sections:

{sections_text}

Each section should be extensive and provide substantial information, insights, and analysis. Ensure coherence with the previous sections and maintain a consistent professional tone. Use relevant examples, data, and references where appropriate to support the content.
"""
    return full_prompt

# Main Application Function
def main():
    st.markdown("# Proposal Documentation Generator")
    
    query_params = st.query_params

    if "token" not in st.session_state:
        if "code" in query_params:
            code = query_params["code"]
            token = get_token_from_code(code)
            if "access_token" in token:
                st.session_state["token"] = token
                user_email = get_user_info(token)
                st.session_state['user_id'] = user_email
                st.rerun() 
            else:
                st.error("Failed to get token")
        else:
            auth_url = get_auth_url()
            st.link_button("Login with Azure AD",auth_url)

    else:
        token = st.session_state["token"]

        # Initialize df in session state if not already present
        if 'df' not in st.session_state:
            columns = ["CLIENT", "PROJECT_NAME", "SOLUTION", "CATEGORY", "SUB_CATEGORY", "IMPORTANCE", "USER_INPUT", "KEY", "USER_ID", "SESSION ID", "DATE_LOADED"]
            st.session_state.df = pd.DataFrame(columns=columns)

        # Sidebar Content for Data Connection (Unchanged)
        with st.sidebar:
            st.header("Connect to Capture Form")
            st.subheader("Upload CSV")
            uploaded_file = st.file_uploader("Choose a CSV file", type=['csv'], key='file_uploader')
            
            if uploaded_file is not None:
                try:
                    data = pd.read_csv(uploaded_file)
                    required_columns_count = 11  
                    if data.shape[1] != required_columns_count:
                        st.error(f"The uploaded CSV does not contain the correct number of columns. Expected {required_columns_count} columns.")
                    elif 'SOLUTION' not in data.columns:
                        st.error("The uploaded CSV file must include a 'SOLUTION' field.")
                    else:
                        data['SOLUTION'] = data['SOLUTION'].replace(to_replace='ILA', value='Information Landscape Assessment')
                        st.session_state.df = data  
                        st.session_state["data_connected"] = True
                        st.success("File uploaded successfully", icon="✅")
                except Exception as e:
                    st.error(f"Failed to read the uploaded file. The error was: {e}")
                
            st.subheader("Connect via Snowflake")
            filter_by_user = st.checkbox("Filter for my user only", value=True)

            # Fetch clients and projects (Unchanged)
            try:
                with conn.cursor() as cur:
                    if filter_by_user:
                        sql_query = """
                            WITH details AS (
                                SELECT DISTINCT CLIENT, PROJECT_NAME, SESSION_ID 
                                FROM CAPTURED_PROPOSAL_DATA
                                WHERE USER_ID = %(user_id)s
                            )
                            SELECT CLIENT, PROJECT_NAME 
                            FROM details 
                            WHERE CLIENT != '' 
                            ORDER BY CLIENT;
                        """
                        cur.execute(sql_query, {'user_id': st.session_state['user_id']})  
                    else:
                        sql_query = """
                            WITH details AS (
                                SELECT DISTINCT CLIENT, PROJECT_NAME, SESSION_ID 
                                FROM CAPTURED_PROPOSAL_DATA
                            )
                            SELECT CLIENT, PROJECT_NAME 
                            FROM details 
                            WHERE CLIENT != '' 
                            ORDER BY CLIENT;
                        """
                        cur.execute(sql_query)

                    rows = cur.fetchall()

                data = process_data(rows)
                client_options = list(data.keys())

                client_name = st.selectbox("Select a Client", client_options, index=0 if client_options else None)
                if client_name:
                    project_options = list(set(data[client_name]))
                    project_name = st.selectbox("Select a Project", project_options, index=0 if project_options else None)

                connect_button = st.button(label="Connect to Database")
                
                if connect_button and client_name and project_name:
                    try:
                        with conn.cursor() as cur:
                            sql = """
                            SELECT *
                            FROM CAPTURED_PROPOSAL_DATA
                            WHERE client = %(client_name)s AND project_name = %(project_name)s;
                            """
                            cur.execute(sql, {'client_name': client_name, 'project_name': project_name})
                            st.session_state.df = cur.fetch_pandas_all()
                            st.session_state["data_connected"] = True
                            
                            if st.session_state.df.empty:
                                st.error("No data returned from Snowflake.")
                            else:
                                st.success("Successfully connected to Snowflake", icon="✅")

                    except Exception as e:
                        st.error(f"Failed to connect to Snowflake: {e}")
            except Exception as e:
                st.error(f"Failed to fetch clients and projects: {e}")

        # Main page changes based on data connection
        if st.session_state.get("data_connected", False):
            st.write("### Data Preview")
            st.write(st.session_state.df)
        else:
            st.write("""Welcome to Decision Inc's Proposal Generator.
            Please follow this guide to make the best use of this product.
            Connect to your data using the sidebar, either by manually uploading a capture form or connecting to our Snowflake database.
            Once a data source has been established, click generate and wait for your proposal.
            Happy proposal generation!""")

        if st.session_state.df.empty and not st.session_state.get("data_connected", False):
            st.write("Please upload a file or connect to Snowflake to continue")
        else:
            st.session_state.df['SOLUTION'] = st.session_state.df['SOLUTION'].replace(to_replace='ILA', value='Information Landscape Assessment')

            # Extract key variables (Unchanged)
            Solution = st.session_state.df['SOLUTION'].drop_duplicates().iloc[0]
            Project = st.session_state.df['PROJECT_NAME'].drop_duplicates().iloc[0]
            client_name = st.session_state.df['CLIENT'].drop_duplicates().iloc[0]

            Sol = st.session_state.df[(st.session_state.df['CATEGORY'] == 'Solutions Aspect')]
            Solution_aspect = '\n'.join(Sol.apply(lambda row: f"{row['SUB_CATEGORY']}: {row['USER_INPUT']}", axis=1))

            KCH = st.session_state.df[(st.session_state.df['CATEGORY']=='Key Challenges') & (st.session_state.df['IMPORTANCE'] == 'High')]
            Key_challenges_high = '\n'.join(KCH.apply(lambda row: f"{row['SUB_CATEGORY']}: {row['USER_INPUT']}", axis=1))

            KCM = st.session_state.df[(st.session_state.df['CATEGORY']=='Key Challenges') & (st.session_state.df['IMPORTANCE'] == 'Moderate')]
            Key_challenges_medium = '\n'.join(KCM.apply(lambda row: f"{row['SUB_CATEGORY']}: {row['USER_INPUT']}", axis=1))

            KCL = st.session_state.df[(st.session_state.df['CATEGORY']=='Key Challenges') & (st.session_state.df['IMPORTANCE'] == 'Low')]
            Key_challenges_low = '\n'.join(KCL.apply(lambda row: f"{row['SUB_CATEGORY']}: {row['USER_INPUT']}", axis=1))

            Add = st.session_state.df[(st.session_state.df['CATEGORY'] == 'Additional Info')]
            Additional_info = '\n'.join(Add['USER_INPUT'])

            # Prepare prompt data (Unchanged)
            prompt_data = {
                'Client_Name': client_name,
                'Project_Name': Project,
                'Solution': Solution,
                'Key_challenges_high': Key_challenges_high,
                'Key_challenges_medium': Key_challenges_medium,
                'Key_challenges_low': Key_challenges_low,
                'Solution_aspect': Solution_aspect,
                'Additional_info': Additional_info
            }

            # Define sections and their overviews (Unchanged)
            sections_part1 = ['Executive Summary', 'Client Background and Problem Statement']
            sections_part2 = ['Solution Overview', 'Scope of Work', 'Proposed Enabling Technology', 'Statement of Work']

            section_overviews = {
                'Executive Summary': (
                    "Provide a detailed introduction to the client's situation, including their industry, market position, and key challenges. "
                    "Explain how our solution addresses their needs and the anticipated benefits. "
                    "Highlight the unique value proposition and why we are the best choice for this project."
                ),
                'Client Background and Problem Statement': (
                    "Thoroughly describe the client's background, including their history, mission, and strategic objectives. "
                    "Detail the specific challenges they are facing, supported by data or examples where possible. "
                    "Explain how these challenges impact their business operations and strategic goals."
                ),
                'Solution Overview': (
                    "Present an in-depth outline of the proposed solution. "
                    "Explain the methodology, processes, and technologies involved. "
                    "Illustrate how the solution addresses each of the client's challenges, and include case studies or success stories from similar projects."
                ),
                'Scope of Work': (
                    "Detail all tasks, deliverables, and methodologies required to implement the solution. "
                    "Break down the project phases, timelines, and resource allocations. "
                    "Include responsibilities, milestones, and key performance indicators (KPIs) to measure success."
                ),
                'Proposed Enabling Technology': (
                    "Discuss in detail the technology stack that will support the proposed solution. "
                    "Explain why these technologies are the best fit for the client’s needs. "
                    "Include technical specifications, integration strategies, and how the technology aligns with the client's existing systems."
                ),
                'Statement of Work': (
                    "Summarize the formal terms of the proposal, including all deliverables, detailed timelines, pricing structures, payment schedules, and expected outcomes. "
                    "Outline the terms and conditions, acceptance criteria, and any assumptions or dependencies. "
                    "Ensure clarity to avoid any ambiguities regarding project execution."
                )
            }

            # Build prompts for part 1 and part 2
            full_prompt_part1 = build_prompt_part1(prompt_data, sections_part1, section_overviews)
            st.session_state.full_prompt_part1 = full_prompt_part1

            # Optional: Add a button to display the full prompt for part 1
            if st.button("Show Full Prompt Part 1", key='show_prompt_part1'):
                if 'full_prompt_part1' in st.session_state:
                    st.markdown("### Full Prompt for Part 1 Sent to OpenAI")
                    st.code(st.session_state.full_prompt_part1)
                else:
                    st.error("No prompt available. Please connect to data first.")

            # Single "Generate Proposal" button
            if st.button("Generate Proposal", key='generate_full_proposal'):
                with st.spinner("Generating the proposal..."):
                    if 'full_prompt_part1' in st.session_state:
                        try:
                            # Generate Part 1
                            messages_part1 = [
                                {"role": "system", "content": SYSTEM_MESSAGE},
                                {"role": "user", "content": st.session_state.full_prompt_part1}
                            ]

                            response_part1 = client.chat.completions.create(
                                model="gpt-4",
                                messages=messages_part1,
                                temperature=0.7,
                                #max_tokens=7500
                            )
                            content_part1 = response_part1.choices[0].message.content.strip()
                            st.session_state.proposal_content_part1 = content_part1

                            # Build prompt for Part 2
                            previous_content = st.session_state.proposal_content_part1
                            full_prompt_part2 = build_prompt_part2(prompt_data, previous_content, sections_part2, section_overviews)
                            st.session_state.full_prompt_part2 = full_prompt_part2

                            # Generate Part 2
                            messages_part2 = [
                                {"role": "system", "content": SYSTEM_MESSAGE},
                                {"role": "user", "content": st.session_state.full_prompt_part2}
                            ]

                            response_part2 = client.chat.completions.create(
                                model="gpt-4",
                                messages=messages_part2,
                                temperature=0.7,
                                #max_tokens=7500
                            )
                            content_part2 = response_part2.choices[0].message.content.strip()
                            st.session_state.proposal_content_part2 = content_part2

                            # Combine both parts for the full proposal
                            full_proposal = st.session_state.proposal_content_part1 + "\n\n" + st.session_state.proposal_content_part2
                            st.session_state.full_proposal = full_proposal

                            # Display the full proposal
                            st.markdown("## Full Proposal")
                            st.write(full_proposal)
                        except Exception as e:
                            st.error(f"Failed to generate the proposal: {e}")
                    else:
                        st.error("No prompt available. Please connect to data first.")

            # Optionally, provide a button to display the full prompt for part 2
            if 'full_proposal' in st.session_state and st.session_state.full_proposal:
                if st.button("Show Full Prompt Part 2", key='show_prompt_part2'):
                    if 'full_prompt_part2' in st.session_state:
                        st.markdown("### Full Prompt for Part 2 Sent to OpenAI")
                        st.code(st.session_state.full_prompt_part2)
                    else:
                        st.error("No prompt available. Please generate the proposal first.")

if __name__ == "__main__":
    main()
