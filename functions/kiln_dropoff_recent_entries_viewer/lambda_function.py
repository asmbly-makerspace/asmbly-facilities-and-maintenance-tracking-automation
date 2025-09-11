import boto3
import json
import os
import requests
from datetime import datetime, timedelta, timezone


# --- Environment Variables ---
# These should be set in the Lambda configuration
# Name of the secret in AWS Secrets Manager containing the API token
SECRET_NAME = os.environ.get('SECRET_NAME', 'clickup/api/token')
# The ID of the ClickUp list where form submissions are created
LIST_ID = os.environ.get('CLICKUP_LIST_KILNDROP_ID')


def get_clickup_api_token():
    """
    Retrieves and cleans the ClickUp API token from AWS Secrets Manager.
    """
    session = boto3.session.Session()
    client = session.client(service_name='secretsmanager')

    try:
        get_secret_value_response = client.get_secret_value(SecretId=SECRET_NAME)
    except Exception as e:
        print(f"ERROR: Unable to retrieve secret from Secrets Manager: {e}")
        raise e

    secret = json.loads(get_secret_value_response['SecretString'])
    token = secret.get('CLICKUP_API_TOKEN')
    
    # Clean the token by stripping leading/trailing whitespace
    if token:
        return token.strip()
    return None


def generate_html_page(tasks):
    """Generates the HTML page to display the recent tasks."""
    
    task_rows = ""
    if not tasks:
        task_rows = '<tr><td colspan="3" class="no-tasks">No submissions found in the last 24 hours. Please try refreshing.</td></tr>'
    else:
        for task in tasks:
            # ClickUp API returns date created as a Unix timestamp in milliseconds
            created_date = datetime.fromtimestamp(int(task['date_created']) / 1000).strftime('%Y-%m-%d %H:%M:%S')
            
            task_rows += f"""
                <tr>
                    <td class="task-id">{task['id']}</td>
                    <td>{task['name']}</td>
                    <td>{created_date}</td>
                </tr>
            """

    # Full HTML document with embedded CSS for styling
    html = f"""
    <!DOCTYPE html>
    <html lang="en">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>Recent Kiln Drop-Offs</title>
        <style>
            @font-face {{
                font-family: "PP Gosha Sans";
                src: url("https://asmbly.org/wp-content/themes/altpico/assets/fonts/PPGoshaSans-Bold.woff2") format("woff2"),
                     url("https://asmbly.org/wp-content/themes/altpico/assets/fonts/PPGoshaSans-Bold.woff") format("woff");
                font-weight: bold;
                font-style: normal;
                font-display: swap;
            }}
            @font-face {{
                font-family: "PP Gosha Sans";
                src: url("https://asmbly.org/wp-content/themes/altpico/assets/fonts/PPGoshaSans-Regular.woff2") format("woff2"),
                     url("https://asmbly.org/wp-content/themes/altpico/assets/fonts/PPGoshaSans-Regular.woff") format("woff");
                font-weight: normal;
                font-style: normal;
                font-display: swap;
            }}

            body {{ font-family: "PP Gosha Sans", -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif; background-color: #F2F4EF; margin: 0; padding: 15px; color: #333; font-size: 16px; }}
            .container {{ max-width: 800px; margin: auto; background: #fff; border-radius: 8px; box-shadow: 0 4px 12px rgba(0,0,0,0.1); padding: 20px; }}
            
            .title-box {{ 
                display: flex;
                align-items: center;
                justify-content: center;
                gap: 20px;
                background-color: #b34a9a; 
                color: white; 
                padding: 15px 25px; 
                border-radius: 8px; 
                margin-bottom: 20px;
            }}
            .header-logo {{ max-height: 60px; width: auto; }}
            h1 {{ font-family: "PP Gosha Sans"; font-weight: 500; text-align: center; font-size: 1.8em; margin: 0; }}
            .subtitle {{ text-align: center; margin-top: 5px; margin-bottom: 25px; color: #555; }}
            
            .instructions {{
                font-size: 1.25em;
                font-weight: 500;
                text-align: center;
                padding: 20px;
                margin: 20px 0;
                color: #2c3e50;
            }}

            table {{ width: 100%; border-collapse: collapse; margin-top: 25px; }}
            th, td {{ padding: 12px 8px; text-align: left; border-bottom: 1px solid #ddd; font-size: 1.1em; }}
            th {{ font-family: "PP Gosha Sans"; font-weight: 500; background-color: #e8ecef; color: #34495e; }}
            tr:hover {{ background-color: #f9f9f9; }}
            .task-id {{ font-weight: 700; color: #2980b9; font-size: 1.4em; font-family: 'Courier New', Courier, monospace; }}
            .no-tasks {{ text-align: center; color: #95a5a6; padding: 20px; }}
            .error-box {{ background-color: #fbeae5; border: 1px solid #e74c3c; color: #c0392b; padding: 20px; border-radius: 5px; text-align: center; }}

            .reload-section {{ text-align: center; margin-top: 30px; }}
            .reload-text {{ margin-bottom: 15px; color: #555; font-size: 1em; }}
            .reload-button {{
                display: inline-block;
                width: auto;
                padding: 15px 45px;
                border: none;
                border-radius: 8px;
                background-color: #27ae60;
                color: white;
                cursor: pointer;
                text-align: center;
                font-family: "PP Gosha Sans";
                font-size: 1.2em;
                font-weight: 500;
                -webkit-tap-highlight-color: transparent; /* Removes tap highlight on mobile */
            }}
            .reload-button:hover {{ background-color: #229954; }}
            .footer-logo {{ display: block; width: 100%; max-width: 125px; margin: 40px auto 10px auto; }}

        </style>
    </head>
    <body>
        <div class="container">
            <div class="title-box">
                <img src="https://asmbly.org/wp-content/uploads/2025/02/ceramics-white.svg" alt="Ceramics Logo" class="header-logo">
                <h1>Recent Kiln Drop-Offs</h1>
            </div>
            <p class="subtitle">Showing drop offs received in the last 24 hours</p>
            
            <div class="instructions">
                Copy your ID from the list below to a slip for each of your pieces.
            </div>

            <table>
                <thead>
                    <tr>
                        <th>Task ID</th>
                        <th>Name</th>
                        <th>Time Submitted</th>
                    </tr>
                </thead>
                <tbody>
                    {task_rows}
                </tbody>
            </table>
            
            <div class="reload-section">
                <p class="reload-text">If your ID is not showing in the list, wait 1-2 minutes and refresh.</p>
                <button class="reload-button" onclick="window.location.reload()">Refresh</button>
            </div>
            
            <img src="https://asmbly.org/wp-content/uploads/2023/12/purple-horizontal.svg" alt="Asmbly Logo" class="footer-logo">

        </div>
    </body>
    </html>
    """
    return html

def generate_error_page(message):
    """Generates a user-friendly HTML error page."""
    error_body = f"""
    <div class="container">
        <div class="error-box">
            <h2>An Error Occurred</h2>
            <p>Could not retrieve the list of submissions.</p>
            <p><small>Error details: {message}</small></p>
        </div>
    </div>
    """
    # Generate the base page with no tasks and inject the error box
    base_html = generate_html_page([])
    # A simple way to replace the main content with the error message
    return base_html.replace(
        '<div class="instructions">', 
        f'{error_body}<div class="instructions" style="display:none;">'
    )


def lambda_handler(event, context):
    """
    Main handler for the Lambda function. Triggered by API Gateway.
    """
    # --- START OF DEBUGGING CODE ---
    print(f"--- DEBUG: Lambda function execution started.")
    print(f"--- DEBUG: List ID from env var 'CLICKUP_LIST_KILNDROP_ID' is: '{LIST_ID}'")
    print(f"--- DEBUG: Secret Name from env var 'SECRET_NAME' is: '{SECRET_NAME}'")
    # --- END OF DEBUGGING CODE ---
    
    # 1. Check for required environment variables
    if not LIST_ID:
        print("ERROR: CLICKUP_LIST_KILNDROP_ID environment variable not set.")
        return {
            "statusCode": 500,
            "headers": {"Content-Type": "text/html"},
            "body": generate_error_page("Server configuration error: Missing List ID."),
        }

    try:
        # 2. Get API token from Secrets Manager
        api_token = get_clickup_api_token()
        
        # --- MORE DEBUGGING CODE ---
        if api_token:
            print(f"--- DEBUG: API Token loaded successfully.")
            # NEW: More detailed logging to verify the token string is clean
            print(f"--- DEBUG: Token Length: {len(api_token)}")
            print(f"--- DEBUG: Token Starts With: '{api_token[:8]}...'")
            print(f"--- DEBUG: Token Ends With: '...{api_token[-4:]}'")
        else:
            print("--- DEBUG ERROR: API Token IS MISSING OR NULL after calling get_clickup_api_token().")
        # --- END OF MORE DEBUGGING CODE ---
        
        # 3. Fetch recent tasks from ClickUp API
        headers = {
            "Authorization": api_token,
            "Content-Type": "application/json"
        }
        
        # MODIFIED: Calculate timestamp for 24 hours ago
        twenty_four_hours_ago = datetime.now(timezone.utc) - timedelta(hours=24)
        timestamp_ms = int(twenty_four_hours_ago.timestamp() * 1000)

        # MODIFIED: Use the timestamp to filter tasks, REMOVED order_by and reverse
        url = f"https://api.clickup.com/api/v2/list/{LIST_ID}/task"
        params = {
            "date_created_gt": timestamp_ms
        }
        
        # --- FINAL DEBUGGING PRINT ---
        print(f"--- DEBUG: Making request to URL: {url} with params: {params}")
        # --- END OF FINAL DEBUGGING PRINT ---
        
        response = requests.get(url, headers=headers, params=params)
        response.raise_for_status()  # Raises an HTTPError for bad responses (4xx or 5xx)
        
        tasks = response.json().get("tasks", [])
        
        # MODIFIED: Sort the tasks manually since the API parameter was removed
        tasks.sort(key=lambda x: int(x.get('date_created', 0)), reverse=True)
        
        # 4. Generate and return the HTML page
        html_body = generate_html_page(tasks)
        
        return {
            "statusCode": 200,
            "headers": {"Content-Type": "text/html"},
            "body": html_body,
        }

    except Exception as e:
        print(f"ERROR: An exception occurred: {e}")
        return {
            "statusCode": 500,
            "headers": {"Content-Type": "text/html"},
            "body": generate_error_page(str(e)),
        }

