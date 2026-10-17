import base64
import hashlib
import html
import logging
import os
import pathlib
import re
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from common.aws import get_secret, get_json_parameter
from common.clickup import get_all_clickup_tasks

logger = logging.getLogger()
logger.setLevel(logging.INFO)


# --- Environment Variables ---
# These should be set in the Lambda configuration
# Name of the secret in AWS Secrets Manager containing the API token
SECRET_NAME = os.environ.get("SECRET_NAME")
# Name of the SSM Parameter containing the ClickUp config (e.g., list ID)
CLICKUP_CERAMICS_CONFIG_PARAMETER_NAME = os.environ.get("CLICKUP_CERAMICS_CONFIG_PARAMETER_NAME")

# The makerspace's local zone. Whether a time is CST or CDT comes from the zone data, not
# from this code. The zone is looked up when a page is built, not at import, so missing
# zone data is logged and shows the error page instead of failing every request.
CENTRAL_TIME_ZONE = "America/Chicago"

# The page shell (styles, header band, Refresh button, footer logo), read once per container.
PAGE_PATH = pathlib.Path(__file__).with_name("page.html")
PAGE_TEMPLATE: str = PAGE_PATH.read_text(encoding="utf-8")
_STYLE_BLOCK = re.compile(r"<style>(.*?)</style>", re.S)


def _style_hash(page: str) -> str:
    """The CSP source for the page's one inline <style> block: 'sha256-<base64 digest>'.

    Raises ValueError when the page has no <style> block or more than one. At import that
    makes every request fail (API Gateway answers 502) instead of serving an unstyled page;
    it does not stop a deploy, so the tests are the guard.
    """
    blocks = _STYLE_BLOCK.findall(page)
    if len(blocks) != 1:
        raise ValueError(f"page.html must have exactly one <style> block, found {len(blocks)}")
    # The browser hashes the element's text exactly as written, so nothing is stripped.
    digest = hashlib.sha256(blocks[0].encode("utf-8")).digest()
    return "'sha256-" + base64.b64encode(digest).decode("ascii") + "'"


# The page runs no script, loads nothing from another site, and has one inline <style>
# block, allowed by its hash.
RESPONSE_HEADERS = {
    "Content-Type": "text/html; charset=utf-8",
    "X-Content-Type-Options": "nosniff",
    "Cache-Control": "no-store",
    "Content-Security-Policy": (
        f"default-src 'none'; style-src {_style_hash(PAGE_TEMPLATE)}; "
        "base-uri 'none'; form-action 'none'; frame-ancestors 'none'"
    ),
}


def _render_page(main_content: str, reload_text: str) -> str:
    """Fills the page shell (page.html) with the main content and the text above the Refresh button.

    Both arguments are trusted HTML; anything from outside must be escaped before it is passed in.
    The main content goes in last, so text from ClickUp is never searched for a placeholder.
    """
    return PAGE_TEMPLATE.replace("__RELOAD_TEXT__", reload_text).replace("__MAIN_CONTENT__", main_content)


def generate_html_page(tasks: list[dict]) -> str:
    """Generates the HTML page to display the recent tasks.

    Each time is shown in US Central with its zone, e.g. "2023-12-31 18:00:00&nbsp;CST".
    The non-breaking space keeps the zone on the same line as the time.
    """
    central = ZoneInfo(CENTRAL_TIME_ZONE)
    task_rows = ""
    if not tasks:
        task_rows = '<tr><td colspan="3" class="no-tasks">No submissions found in the last 24 hours. Please try refreshing.</td></tr>'
    else:
        for task in tasks:
            # ClickUp API returns date created as a Unix timestamp in milliseconds (UTC)
            created_utc = datetime.fromtimestamp(int(task['date_created']) / 1000, timezone.utc)
            created_date = created_utc.astimezone(central).strftime('%Y-%m-%d %H:%M:%S&nbsp;%Z')
            
            # Use the custom_id if it exists, otherwise fall back to the standard id
            # (ClickUp sends "custom_id": null when a list has no custom IDs)
            display_id = html.escape(str(task.get('custom_id') or task['id']))
            task_name = html.escape(str(task['name']))

            task_rows += f"""
                <tr>
                    <td class="task-id">{display_id}</td>
                    <td>{task_name}</td>
                    <td>{created_date}</td>
                </tr>
            """

    main_content = f"""<p class="subtitle">Showing drop offs received in the last 24 hours</p>
            
            <div class="instructions">
                Please write your Name and your ID from the list below to a slip for each of your pieces.
            </div>

            <table>
                <thead>
                    <tr>
                        <th>Drop-Off ID</th>
                        <th>Name</th>
                        <th>Time Submitted</th>
                    </tr>
                </thead>
                <tbody>
                    {task_rows}
                </tbody>
            </table>"""
    return _render_page(main_content, "If your ID is not showing in the list, wait 1-2 minutes and refresh.")


def generate_error_page() -> str:
    """Generates a user-friendly HTML error page with no list and no error details."""
    error_box = """<div class="error-box">
                <h2>An Error Occurred</h2>
                <p>Could not retrieve the list of submissions.</p>
            </div>"""
    return _render_page(error_box, "Please wait 1-2 minutes and refresh.")


def html_response(status_code: int, body: str) -> dict:
    """Builds an API Gateway response for an HTML page with the security headers."""
    return {
        "statusCode": status_code,
        "headers": dict(RESPONSE_HEADERS),
        "body": body,
    }


def lambda_handler(event: dict, context: object) -> dict:
    """
    Main handler for the Lambda function. Triggered by API Gateway.
    """
    # 1. Check for required environment variables
    if not SECRET_NAME:
        logger.error("SECRET_NAME environment variable not set")
        return html_response(500, generate_error_page())
    if not CLICKUP_CERAMICS_CONFIG_PARAMETER_NAME:
        logger.error("CLICKUP_CERAMICS_CONFIG_PARAMETER_NAME environment variable not set")
        return html_response(500, generate_error_page())

    try:
        # 2. Get ClickUp List ID from SSM Parameter Store
        list_id = get_json_parameter(CLICKUP_CERAMICS_CONFIG_PARAMETER_NAME, "list_id")
        logger.info("Loaded ClickUp list ID %s", list_id)

        # 3. Get API token from Secrets Manager
        api_token = get_secret(SECRET_NAME, 'CLICKUP_API_TOKEN')

        if not api_token:
            logger.error("ClickUp API token missing from secret")
            return html_response(500, generate_error_page())

        # 4. Fetch recent tasks from ClickUp API
        twenty_four_hours_ago = datetime.now(timezone.utc) - timedelta(hours=24)
        timestamp_ms = int(twenty_four_hours_ago.timestamp() * 1000)
        logger.info("Fetching tasks created after %s (timestamp: %s)", twenty_four_hours_ago.isoformat(), timestamp_ms)

        tasks = get_all_clickup_tasks(list_id, api_token, date_created_gt_ms=timestamp_ms)
        logger.info("Retrieved %s tasks from ClickUp", len(tasks))

        # Sort by date_created descending (newest first)
        tasks.sort(key=lambda x: int(x.get('date_created', 0)), reverse=True)

        # 5. Generate and return the HTML page
        html_body = generate_html_page(tasks)

        return html_response(200, html_body)

    except Exception:
        logger.exception("Failed to load kiln drop-offs")
        return html_response(500, generate_error_page())
