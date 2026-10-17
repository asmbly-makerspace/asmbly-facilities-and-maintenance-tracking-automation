import base64
import hashlib
import importlib
import json
import logging
import pathlib
import re
from unittest.mock import MagicMock, patch

import pytest

# Now we can import the lambda function module directly
from functions.ceramics.kiln_dropoff_recent_entries_viewer import lambda_function

LAMBDA_FUNCTION_PATH = "functions.ceramics.kiln_dropoff_recent_entries_viewer.lambda_function"


@pytest.fixture
def mock_env_vars(monkeypatch):
    """Mock environment variables for the Lambda function."""
    monkeypatch.setenv('SECRET_NAME', 'test/clickup/token')
    monkeypatch.setenv('CLICKUP_CERAMICS_CONFIG_PARAMETER_NAME', '/test/config/clickup/ceramics')


@pytest.fixture
def reload_lambda_function(mock_env_vars):
    """Reloads the lambda function module to apply mocked environment variables."""
    importlib.reload(lambda_function)
    yield


@pytest.fixture
def mock_tasks_from_file():
    """Loads mock ClickUp task data from the provided JSON fixture."""
    fixture_path = pathlib.Path(__file__).parent / "fixtures" / "clickup_dropofftasks_response.json"
    # Return a function that re-opens and re-loads the file to ensure a fresh, deep copy for each test
    def _loader():
        with open(fixture_path, 'r') as f:
            return json.load(f)
    return _loader


def test_generate_html_page_with_tasks(mock_tasks_from_file):
    """Test HTML page generation with a list of tasks."""
    mock_data = mock_tasks_from_file()
    tasks = mock_data['tasks']
    
    # The fixture has 10 tasks. Let's create timestamps for them.
    # Base timestamp: 2024-01-01 00:00:00 UTC
    base_ts = 1704067200000 
    for i, task in enumerate(tasks):
        task['date_created'] = str(base_ts + i * 1000) # Increment by 1 second

    # Mimic the sorting that happens in the lambda_handler
    tasks.sort(key=lambda x: int(x.get('date_created', 0)), reverse=True)

    html = lambda_function.generate_html_page(tasks)

    assert "<h1>Recent Kiln Drop-Offs</h1>" in html
    # The last task in the fixture ('Customer J') has the latest date and should appear first.
    # The first task ('Customer A') has the earliest date and should appear last.
    # After sorting, the last task in the fixture ('Customer J') should appear first in the HTML.
    assert html.find("Customer J") < html.find("Customer A")
    assert "No submissions found" not in html


def test_time_submitted_is_shown_in_central_time_with_zone() -> None:
    """Drop-off times are shown in US Central with CST or CDT, not in UTC."""
    tasks = [
        {'id': 'winter', 'custom_id': 'KO-1', 'name': 'Customer W', 'date_created': '1704067200000'},
        {'id': 'summer', 'custom_id': 'KO-2', 'name': 'Customer S', 'date_created': '1720094400000'},
    ]

    page = lambda_function.generate_html_page(tasks)

    assert '2023-12-31 18:00:00&nbsp;CST' in page
    assert '2024-07-04 07:00:00&nbsp;CDT' in page
    assert '2024-01-01 00:00:00' not in page
    assert '2024-07-04 12:00:00' not in page


def test_generate_html_page_no_tasks():
    """Test HTML page generation with no tasks."""
    html = lambda_function.generate_html_page([])
    assert "<h1>Recent Kiln Drop-Offs</h1>" in html
    assert 'No submissions found in the last 24 hours' in html


def test_generate_error_page():
    """Test the generation of a user-friendly error page."""
    html = lambda_function.generate_error_page()
    assert "<h2>An Error Occurred</h2>" in html
    assert "Could not retrieve the list of submissions." in html
    assert "Error details" not in html


@patch(f'{LAMBDA_FUNCTION_PATH}.get_secret')
@patch(f'{LAMBDA_FUNCTION_PATH}.get_all_clickup_tasks')
@patch(f'{LAMBDA_FUNCTION_PATH}.get_json_parameter')
def test_lambda_handler_success(mock_get_json_param, mock_get_all_clickup_tasks, mock_get_secret, reload_lambda_function, mock_tasks_from_file):
    """Test the full success path of the lambda_handler."""
    # Arrange
    mock_get_secret.return_value = 'fake-token'
    mock_data = mock_tasks_from_file() # Get a fresh copy of the data
    mock_get_json_param.return_value = '123456789' # Mock the list ID

    # We need to add date_created to all tasks for this to work because the fixture lacks it.
    for i, task in enumerate(mock_data['tasks']):
        task['date_created'] = str(1704067200000 + i * 1000)  # Staggered timestamps
    mock_get_all_clickup_tasks.return_value = mock_data['tasks']

    # Act
    result = lambda_function.lambda_handler({}, None)

    # Assert mocks were called
    mock_get_json_param.assert_called_with('/test/config/clickup/ceramics', 'list_id')

    # Assert
    assert result['statusCode'] == 200
    assert result['headers']['Content-Type'] == 'text/html; charset=utf-8'
    assert "<h1>Recent Kiln Drop-Offs</h1>" in result['body']
    assert "KO-FAKE-001" in result['body'] # Check for task data
    assert "Customer A" in result['body']
    
    # Check that sorting happened (the fixture is not sorted by date)
    # The last task in the fixture ('Customer J') has the latest timestamp, so it should appear first in the HTML.
    assert result['body'].find('Customer J') < result['body'].find('Customer A')


@patch(f'{LAMBDA_FUNCTION_PATH}.get_secret')
@patch(f'{LAMBDA_FUNCTION_PATH}.get_all_clickup_tasks')
@patch(f'{LAMBDA_FUNCTION_PATH}.get_json_parameter')
def test_lambda_handler_clickup_api_error(mock_get_json_param, mock_get_all_clickup_tasks, mock_get_secret, reload_lambda_function):
    """Test the handler's response to a ClickUp API error."""
    # Arrange
    mock_get_secret.return_value = 'fake-token'
    mock_get_json_param.return_value = '123456789'
    mock_get_all_clickup_tasks.side_effect = ValueError("401 Client Error: Unauthorized for url")

    # Act
    result = lambda_function.lambda_handler({}, None)

    # Assert
    assert result['statusCode'] == 500
    assert "<h2>An Error Occurred</h2>" in result['body']
    assert "Could not retrieve the list of submissions." in result['body']
    assert "401 Client Error: Unauthorized for url" not in result['body']

def test_lambda_handler_missing_env_var(reload_lambda_function, monkeypatch, caplog):
    """Test the handler's response when a required environment variable is missing."""
    # Arrange
    monkeypatch.delenv('CLICKUP_CERAMICS_CONFIG_PARAMETER_NAME')
    importlib.reload(lambda_function) # Reload to pick up the deleted env var

    # Act
    with caplog.at_level(logging.INFO):
        result = lambda_function.lambda_handler({}, None)

    # Assert
    assert result['statusCode'] == 500
    assert "<h2>An Error Occurred</h2>" in result['body']
    assert "Could not retrieve the list of submissions." in result['body']
    assert "CLICKUP_CERAMICS_CONFIG_PARAMETER_NAME" not in result['body']
    assert "Server configuration error" not in result['body']
    assert "CLICKUP_CERAMICS_CONFIG_PARAMETER_NAME" in caplog.text


def test_lambda_handler_missing_secret_name(reload_lambda_function, monkeypatch, caplog):
    """A missing SECRET_NAME gives the generic error page and names the variable only in the log."""
    monkeypatch.delenv('SECRET_NAME')
    importlib.reload(lambda_function)

    with caplog.at_level(logging.INFO):
        result = lambda_function.lambda_handler({}, None)

    assert result['statusCode'] == 500
    assert "Could not retrieve the list of submissions." in result['body']
    assert "SECRET_NAME" not in result['body']
    assert "Server configuration error" not in result['body']
    assert "SECRET_NAME" in caplog.text


@patch(f'{LAMBDA_FUNCTION_PATH}.get_secret')
@patch(f'{LAMBDA_FUNCTION_PATH}.get_json_parameter')
def test_lambda_handler_secret_manager_error(mock_get_json_param, mock_get_secret, reload_lambda_function):
    """Test the handler's response to a Secrets Manager error."""
    # Arrange
    # We need to mock the SSM call so the function can proceed to the secrets call
    mock_get_json_param.return_value = '123456789'
    mock_get_secret.side_effect = Exception("Could not connect to Secrets Manager")

    # Act
    result = lambda_function.lambda_handler({}, None)

    # Assert
    assert result['statusCode'] == 500
    assert "<h2>An Error Occurred</h2>" in result['body']
    assert "Could not retrieve the list of submissions." in result['body']
    assert "Could not connect to Secrets Manager" not in result['body']


def test_generate_html_page_escapes_task_name_and_id():
    """Form text and IDs are escaped before they go into the page (#74)."""
    tasks = [{
        'id': 'abc123',
        'custom_id': 'KO-<b>1</b>',
        'name': '<script>alert(1)</script>',
        'date_created': '1704067200000',
    }]

    page = lambda_function.generate_html_page(tasks)

    assert '<script>alert(1)</script>' not in page
    assert 'KO-<b>1</b>' not in page
    assert '&lt;script&gt;alert(1)&lt;/script&gt;' in page
    assert 'KO-&lt;b&gt;1&lt;/b&gt;' in page


@patch(f'{LAMBDA_FUNCTION_PATH}.get_secret')
@patch(f'{LAMBDA_FUNCTION_PATH}.get_all_clickup_tasks')
@patch(f'{LAMBDA_FUNCTION_PATH}.get_json_parameter')
def test_lambda_handler_error_page_hides_exception_text(mock_get_json_param, mock_get_all_clickup_tasks, mock_get_secret, reload_lambda_function, caplog):
    """The error page never shows the exception's text; it goes to the log instead (#74)."""
    marker = "ClickUp API HTTP Error: 401 Unauthorized - Details: {\"err\": \"Token invalid\", \"url\": \"list/123456789/task\"}"
    mock_get_secret.return_value = 'fake-token'
    mock_get_json_param.return_value = '123456789'
    mock_get_all_clickup_tasks.side_effect = ValueError(marker)

    with caplog.at_level(logging.INFO):
        result = lambda_function.lambda_handler({}, None)

    assert result['statusCode'] == 500
    body = result['body']
    assert "Could not retrieve the list of submissions." in body
    assert marker not in body
    assert "Token invalid" not in body
    assert "401" not in body
    assert "123456789" not in body
    assert "Error details" not in body
    assert any(r.exc_info and marker in str(r.exc_info[1]) for r in caplog.records)


@patch(f'{LAMBDA_FUNCTION_PATH}.get_secret')
@patch(f'{LAMBDA_FUNCTION_PATH}.get_all_clickup_tasks')
@patch(f'{LAMBDA_FUNCTION_PATH}.get_json_parameter')
def test_lambda_handler_empty_token_returns_generic_500(mock_get_json_param, mock_get_all_clickup_tasks, mock_get_secret, reload_lambda_function, caplog):
    """An empty API token stops before ClickUp is called and shows the generic error page."""
    mock_get_json_param.return_value = '123456789'
    mock_get_secret.return_value = ""

    with caplog.at_level(logging.INFO):
        result = lambda_function.lambda_handler({}, None)

    mock_get_all_clickup_tasks.assert_not_called()
    assert result['statusCode'] == 500
    assert "Could not retrieve the list of submissions." in result['body']
    assert "ClickUp API token missing from secret" in caplog.text


def test_generate_html_page_null_custom_id_shows_task_id():
    """ClickUp sends "custom_id": null on lists without custom IDs; the task ID is shown instead."""
    tasks = [{'id': 'abc123', 'custom_id': None, 'name': 'Customer Z', 'date_created': '1704067200000'}]

    page = lambda_function.generate_html_page(tasks)

    assert '<td class="task-id">abc123</td>' in page
    assert 'None' not in page


def test_generate_html_page_escapes_quotes_and_ampersands():
    """Ampersands and quotes in a name are escaped."""
    tasks = [{'id': 'abc123', 'custom_id': 'KO-1', 'name': 'O\'Brien & "Sons"', 'date_created': '1704067200000'}]

    page = lambda_function.generate_html_page(tasks)

    assert 'O&#x27;Brien &amp; &quot;Sons&quot;' in page
    assert 'O\'Brien & "Sons"' not in page


PAGE_HTML = (pathlib.Path(lambda_function.__file__).parent / "page.html").read_text(encoding="utf-8")
STYLE_BLOCK = re.compile(r"<style>(.*?)</style>", re.S)


def _sha256_source(text: str) -> str:
    """The CSP hash source for this text, computed here rather than taken from the module."""
    return "'sha256-" + base64.b64encode(hashlib.sha256(text.encode("utf-8")).digest()).decode("ascii") + "'"


A_TASK = {'id': 'abc123', 'custom_id': 'KO-1', 'name': 'Customer Z', 'date_created': '1704067200000'}


def _pages() -> dict[str, str]:
    """The three pages the function serves: the empty list, a list with a drop-off, and the error page."""
    return {
        'empty': lambda_function.generate_html_page([]),
        'tasks': lambda_function.generate_html_page([dict(A_TASK)]),
        'error': lambda_function.generate_error_page(),
    }


def _directives(csp: str) -> dict[str, str]:
    """A Content-Security-Policy as {directive: sources}."""
    directives = {}
    for part in csp.split(";"):
        name, _, value = part.strip().partition(" ")
        assert name not in directives, name
        directives[name] = value.strip()
    return directives


# Tightened by plan kiln-dropoff-ceramics-branding: no asmbly.org, no 'unsafe-inline'.
EXPECTED_CSP = (
    f"default-src 'none'; style-src {_sha256_source(STYLE_BLOCK.findall(PAGE_HTML)[0])}; "
    "base-uri 'none'; form-action 'none'; frame-ancestors 'none'"
)
EXPECTED_HEADERS = {
    "Content-Type": "text/html; charset=utf-8",
    "X-Content-Type-Options": "nosniff",
    "Cache-Control": "no-store",
    "Content-Security-Policy": EXPECTED_CSP,
}


@patch(f'{LAMBDA_FUNCTION_PATH}.get_secret')
@patch(f'{LAMBDA_FUNCTION_PATH}.get_all_clickup_tasks')
@patch(f'{LAMBDA_FUNCTION_PATH}.get_json_parameter')
def test_lambda_handler_sets_csp_header(mock_get_json_param, mock_get_all_clickup_tasks, mock_get_secret, reload_lambda_function, monkeypatch, mock_tasks_from_file):
    """The page and every error page carry the same security headers and no script (#74)."""
    mock_get_json_param.return_value = '123456789'
    mock_data = mock_tasks_from_file()
    for i, task in enumerate(mock_data['tasks']):
        task['date_created'] = str(1704067200000 + i * 1000)

    results = {}

    mock_get_secret.return_value = 'fake-token'
    mock_get_all_clickup_tasks.return_value = mock_data['tasks']
    results['success'] = lambda_function.lambda_handler({}, None)

    mock_get_all_clickup_tasks.side_effect = ValueError("boom")
    results['clickup_error'] = lambda_function.lambda_handler({}, None)

    mock_get_secret.return_value = ""
    results['empty_token'] = lambda_function.lambda_handler({}, None)

    monkeypatch.delenv('CLICKUP_CERAMICS_CONFIG_PARAMETER_NAME')
    importlib.reload(lambda_function)
    results['missing_config'] = lambda_function.lambda_handler({}, None)

    monkeypatch.delenv('SECRET_NAME')
    importlib.reload(lambda_function)
    results['missing_secret'] = lambda_function.lambda_handler({}, None)

    assert results['success']['statusCode'] == 200
    for name, result in results.items():
        if name != 'success':
            assert result['statusCode'] == 500, name
        assert result['headers'] == EXPECTED_HEADERS, name
        assert 'onclick' not in result['body'], name
        assert '<script' not in result['body'], name
        assert '<a class="reload-button" href="">Refresh</a>' in result['body'], name


def test_pages_load_nothing_from_outside() -> None:
    """No page loads a font, image, stylesheet or script, from asmbly.org or anywhere else."""
    for name, page in _pages().items():
        for forbidden in ("http://", "https://", "<img", "<link", "@font-face", "url(", "<script"):
            assert forbidden not in page, (name, forbidden)


def test_pages_have_no_unformatted_braces():
    """Every page is the filled shell: its token block, no doubled braces, no placeholder left."""
    tasks = [{'id': 'abc123', 'custom_id': 'KO-1', 'name': 'Customer Z', 'date_created': '1704067200000'}]
    pages = {
        'empty': lambda_function.generate_html_page([]),
        'tasks': lambda_function.generate_html_page(tasks),
        'error': lambda_function.generate_error_page(),
    }
    for name, page in pages.items():
        assert '{{' not in page, name
        assert '}}' not in page, name
        assert ':root {' in page, name
        assert '__MAIN_CONTENT__' not in page, name
        assert '__RELOAD_TEXT__' not in page, name


def test_generate_error_page_shows_no_list_or_empty_message():
    """The error page shows only the error, not the empty list's "No submissions found" row."""
    page = lambda_function.generate_error_page()

    assert "<h2>An Error Occurred</h2>" in page
    assert "Could not retrieve the list of submissions." in page
    assert "No submissions found" not in page
    assert "<table" not in page
    assert "Showing drop offs received in the last 24 hours" not in page
    assert "If your ID is not showing in the list" not in page
    assert "display:none" not in page
    assert page.count('class="container"') == 1


@patch(f'{LAMBDA_FUNCTION_PATH}.get_secret')
@patch(f'{LAMBDA_FUNCTION_PATH}.get_all_clickup_tasks')
@patch(f'{LAMBDA_FUNCTION_PATH}.get_json_parameter')
def test_lambda_handler_error_pages_show_no_list(mock_get_json_param, mock_get_all_clickup_tasks, mock_get_secret, reload_lambda_function, monkeypatch):
    """Every error path returns the error page without the list or "No submissions found"."""
    mock_get_json_param.return_value = '123456789'
    results = {}

    mock_get_secret.return_value = 'fake-token'
    mock_get_all_clickup_tasks.side_effect = ValueError("boom")
    results['clickup_error'] = lambda_function.lambda_handler({}, None)

    mock_get_secret.return_value = ""
    results['empty_token'] = lambda_function.lambda_handler({}, None)

    # setattr, not delenv and reload, so pytest restores the module-level values after the test
    monkeypatch.setattr(lambda_function, 'CLICKUP_CERAMICS_CONFIG_PARAMETER_NAME', None)
    results['missing_config'] = lambda_function.lambda_handler({}, None)

    monkeypatch.setattr(lambda_function, 'SECRET_NAME', None)
    results['missing_secret'] = lambda_function.lambda_handler({}, None)

    for name, result in results.items():
        assert result['statusCode'] == 500, name
        assert "Could not retrieve the list of submissions." in result['body'], name
        assert "No submissions found" not in result['body'], name
        assert "<table" not in result['body'], name


# ---- The page shell and its Content-Security-Policy (plan kiln-dropoff-ceramics-branding) ----


def _responses_on_every_path(
    mock_get_json_param: MagicMock,
    mock_get_all_clickup_tasks: MagicMock,
    mock_get_secret: MagicMock,
    monkeypatch: pytest.MonkeyPatch,
    tasks: list[dict],
) -> dict[str, dict]:
    """The handler's response on the success path and on each error path."""
    mock_get_json_param.return_value = '123456789'
    results = {}

    mock_get_secret.return_value = 'fake-token'
    mock_get_all_clickup_tasks.return_value = tasks
    results['success'] = lambda_function.lambda_handler({}, None)

    mock_get_all_clickup_tasks.side_effect = ValueError("boom")
    results['clickup_error'] = lambda_function.lambda_handler({}, None)

    mock_get_secret.return_value = ""
    results['empty_token'] = lambda_function.lambda_handler({}, None)

    monkeypatch.setattr(lambda_function, 'CLICKUP_CERAMICS_CONFIG_PARAMETER_NAME', None)
    results['missing_config'] = lambda_function.lambda_handler({}, None)

    monkeypatch.setattr(lambda_function, 'SECRET_NAME', None)
    results['missing_secret'] = lambda_function.lambda_handler({}, None)
    return results


@patch(f'{LAMBDA_FUNCTION_PATH}.get_secret')
@patch(f'{LAMBDA_FUNCTION_PATH}.get_all_clickup_tasks')
@patch(f'{LAMBDA_FUNCTION_PATH}.get_json_parameter')
def test_csp_style_hash_matches_served_style(
    mock_get_json_param: MagicMock,
    mock_get_all_clickup_tasks: MagicMock,
    mock_get_secret: MagicMock,
    reload_lambda_function: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """On every path, the CSP's style hash is the hash of the one <style> block in the body sent."""
    results = _responses_on_every_path(mock_get_json_param, mock_get_all_clickup_tasks, mock_get_secret, monkeypatch, [dict(A_TASK)])

    assert results['success']['statusCode'] == 200
    for name, result in results.items():
        csp = result['headers']['Content-Security-Policy']
        styles = STYLE_BLOCK.findall(result['body'])
        assert len(styles) == 1, name
        assert _directives(csp)['style-src'] == _sha256_source(styles[0]), name
        for forbidden in ("'unsafe-inline'", "font-src", "img-src", "script-src", "data:", "https:", "asmbly.org"):
            assert forbidden not in csp, (name, forbidden)


def test_csp_is_no_looser_than_before() -> None:
    """Every directive is 'none' except style-src, which is only the style block's hash."""
    directives = _directives(lambda_function.RESPONSE_HEADERS['Content-Security-Policy'])

    assert set(directives) == {'default-src', 'style-src', 'base-uri', 'form-action', 'frame-ancestors'}
    for name, value in directives.items():
        if name == 'style-src':
            assert re.fullmatch(r"'sha256-[A-Za-z0-9+/]{43}='", value), value
        else:
            assert value == "'none'", name


def test_style_hash_rejects_zero_or_two_style_blocks() -> None:
    assert lambda_function._style_hash("<style>\n  a { }\n</style>") == _sha256_source("\n  a { }\n")
    with pytest.raises(ValueError):
        lambda_function._style_hash("<html><body></body></html>")
    with pytest.raises(ValueError):
        lambda_function._style_hash("<style>a { }</style><style>b { }</style>")


def test_placeholder_in_task_name_is_shown_as_text() -> None:
    """A drop-off named like a placeholder shows that name; the shell is filled once."""
    tasks = [
        {'id': 'a1', 'custom_id': 'KO-1', 'name': '__RELOAD_TEXT__', 'date_created': '1704067200000'},
        {'id': 'a2', 'custom_id': 'KO-2', 'name': '__MAIN_CONTENT__', 'date_created': '1704067200000'},
    ]

    page = lambda_function.generate_html_page(tasks)

    assert '<td>__RELOAD_TEXT__</td>' in page
    assert '<td>__MAIN_CONTENT__</td>' in page
    assert page.count('If your ID is not showing in the list, wait 1-2 minutes and refresh.') == 1
    assert page.count('<table>') == 1


def test_page_template_has_each_placeholder_once() -> None:
    assert lambda_function.PAGE_TEMPLATE == PAGE_HTML
    assert PAGE_HTML.count('__MAIN_CONTENT__') == 1
    assert PAGE_HTML.count('__RELOAD_TEXT__') == 1
    assert PAGE_HTML.index('__MAIN_CONTENT__') < PAGE_HTML.index('__RELOAD_TEXT__')


def test_header_band_shows_ceramics_icon_and_title() -> None:
    """The band holds the ceramics icon, then the title, and nothing else (README Decision 4)."""
    icon = '<svg class="ceramics-icon" role="img" aria-label="Ceramics" viewBox="0 0 38.4 38.4" focusable="false">'
    for name, page in _pages().items():
        band = page[page.index('<header class="brand-band">') : page.index('</header>')]
        assert band.count(icon) == 1, name
        assert band.index(icon) < band.index('<h1>Recent Kiln Drop-Offs</h1>'), name
        assert re.sub(r"<[^>]+>", " ", band).split() == ['Recent', 'Kiln', 'Drop-Offs'], name
        svg = band[band.index(icon) : band.index('</svg>')]
        assert svg.count('<path ') == 1
        assert re.search(r'<path d="M0,0v38\.4h38\.4V0H0Z', svg)
        for forbidden in ('fill', 'stroke', 'style', 'xmlns', 'href', '<image'):
            assert forbidden not in svg, forbidden


def test_footer_shows_asmbly_logo() -> None:
    """The official logo, as on the class photo upload page, at the foot of every page."""
    logo = '<svg class="logo" role="img" aria-label="Asmbly Makerspace" viewBox="0 0 443.61 122.16" focusable="false">'
    for name, page in _pages().items():
        footer = page[page.index('<footer class="site-footer">') : page.index('</footer>')]
        assert page.count('<svg class="logo"') == 1, name
        assert footer.count(logo) == 1, name
        svg = footer[footer.index(logo) : footer.index('</svg>')]
        assert svg.count('<path ') == 17
        assert 'd="m122.16,77.71V0H0v44.44h20.85' in svg  # the official icon path
        for forbidden in ('fill', 'stroke', 'style', 'xmlns', 'href', '<image'):
            assert forbidden not in svg, forbidden
    logo_rule = _rule('.logo')
    assert 'color: var(--logo-colour)' in logo_rule and 'fill: currentColor' in logo_rule


def test_error_page_shares_the_shell() -> None:
    """The error page has the same band, icon, Refresh button and logo as the list page."""
    before, rest = PAGE_HTML.split('__MAIN_CONTENT__')
    middle, after = rest.split('__RELOAD_TEXT__')
    for name in ('empty', 'error'):
        page = _pages()[name]
        assert page.startswith(before), name
        assert middle in page, name
        assert page.endswith(after), name
    assert '<header class="brand-band">' in before and '<svg class="ceramics-icon"' in before
    assert '<a class="reload-button" href="">Refresh</a>' in after and '<svg class="logo"' in after


def test_page_html_is_packaged_next_to_the_handler() -> None:
    """page.html sits in the folder the template's CodeUri packages."""
    folder = pathlib.Path(lambda_function.__file__).parent
    assert lambda_function.PAGE_PATH == folder / 'page.html'
    assert lambda_function.PAGE_PATH.is_file()
    repo = folder.parents[2]
    template = (repo / 'templates' / 'ceramics.yaml').read_text(encoding='utf-8')
    # The function's resource: its name line and the indented lines under it.
    function = re.search(r'\n  KilnDropoffRecentEntriesViewerFunction:\n((?:    .*\n|\s*\n)+)', template)
    assert function is not None
    assert '      CodeUri: ../functions/ceramics/kiln_dropoff_recent_entries_viewer/\n' in function.group(1)


def test_page_with_50_dropoffs_is_under_60kb() -> None:
    tasks = [
        {'id': f'id{i}', 'custom_id': f'KO-{1000 + i}', 'name': 'N' * 60, 'date_created': str(1704067200000 + i)}
        for i in range(50)
    ]

    assert len(lambda_function.generate_html_page(tasks).encode('utf-8')) < 60 * 1024


def test_long_name_is_in_a_wrapping_cell() -> None:
    """A 60-character name with no space sits in a plain cell, which wraps anywhere (#133)."""
    name = 'W' * 60
    page = lambda_function.generate_html_page([{'id': 'a1', 'custom_id': 'KO-1', 'name': name, 'date_created': '1704067200000'}])

    assert f'<td>{name}</td>' in page
    assert 'overflow-wrap: anywhere' in _rule('td')


# ---- Brand tokens, contrast and layout (copied from the class photo upload page's tests, adapted) ----

CSS_COMMENT = re.compile(r"/\*.*?\*/", re.S)
TOKEN = re.compile(r"(--[\w-]+)\s*:\s*([^;]+);")
VAR_REFERENCE = re.compile(r"var\(\s*(--[\w-]+)\s*\)")
HEX_COLOUR = re.compile(r"#[0-9a-fA-F]{3,8}(?![\w-])")
PURE_WHITE_OR_BLACK = re.compile(r"(?<![\w-])(white|black)(?![\w-])", re.I)
# Outside :root a declaration's value may hold only var() references, 0, 100% and these
# CSS keywords, none of which can carry a colour or a length.
ALLOWED_VALUE_WORDS = {
    "anywhere", "auto", "block", "border-box", "center", "collapse", "currentColor", "flex", "inline-block",
    "inline-flex", "left", "none", "normal", "nowrap", "solid", "top", "wrap",
}
TOKEN_VALUE = re.compile(r"#[0-9a-fA-F]{6}|var\(--[\w-]+\)|\d*\.?\d+(?:rem|px)?")
FONT_STACK = re.compile(r'(?:"[\w ]+"|[\w-]+)(?:, (?:"[\w ]+"|[\w-]+))*')
GLYPH_TOKEN = re.compile(r'"[^"\s]" / ""')
# Tokens no rule reads through var(), with the reason.
RESERVED_TOKENS = {
    "--lasers": "the parent of --lasers-shade and --lasers-20 (test_derived_tokens_follow_the_formula)",
}
# Literal values two tokens of different kinds may share, with the reason.
SHARED_LITERALS = {
    "1rem": {"--font-size-body", "--space-4"},  # body text size; a spacing step
}
SVG_ATTRIBUTES = {"aria-label", "class", "d", "focusable", "role", "viewBox"}
ROOT_FONT_PX = 16

BRAND_COLOURS = {
    "--asmbly-purple": "#292D6A",
    "--asmbly-white": "#F2F4EF",
    "--midnight-black": "#171d1a",
    "--ceramics": "#b34a9a",
    "--lasers": "#D33E43",
}
# (token, first colour, second colour, share of the first): the derivation formula.
DERIVED_COLOURS = [
    ("--ceramics-shade", "--ceramics", "--midnight-black", 0.8),
    ("--ceramics-shade-60", "--ceramics", "--midnight-black", 0.6),
    ("--ceramics-40", "--ceramics", "--asmbly-white", 0.4),
    ("--ceramics-20", "--ceramics", "--asmbly-white", 0.2),
    ("--ceramics-10", "--ceramics", "--asmbly-white", 0.1),
    ("--lasers-shade", "--lasers", "--midnight-black", 0.8),
    ("--lasers-20", "--lasers", "--asmbly-white", 0.2),
]
# (foreground, background, minimum WCAG 2.1 contrast ratio): the README's contrast table.
CONTRAST_PAIRS = [
    ("--on-accent", "--accent", 3.0),  # h1 (large text) and icon (non-text) in the band
    ("--text", "--page-bg", 4.5),
    ("--accent-strong", "--page-bg", 4.5),  # drop-off IDs
    ("--accent-strong", "--row-hover-bg", 4.5),
    ("--text", "--row-hover-bg", 4.5),
    ("--text", "--table-head-bg", 4.5),
    ("--on-accent", "--accent-strong", 4.5),  # Refresh button
    ("--on-accent", "--accent-hover", 4.5),
    ("--text", "--error-bg", 4.5),
    ("--error-edge", "--page-bg", 3.0),
    ("--error-edge", "--error-bg", 3.0),  # the edge, and the glyph in the 20px bold h2
    ("--focus", "--page-bg", 3.0),
    ("--logo-colour", "--page-bg", 3.0),
]
MEDIA_BLOCK = re.compile(r"@media([^{]*)\{((?:[^{}]*\{[^{}]*\})*[^{}]*)\}")
RULE = re.compile(r"([^{}]+)\{([^{}]*)\}")
HOVER_MEDIA = "(hover: hover)"


def _style() -> str:
    """The text of the page's one <style> block."""
    blocks = STYLE_BLOCK.findall(PAGE_HTML)
    assert len(blocks) == 1
    return blocks[0]


def _css() -> str:
    """The stylesheet without comments."""
    return CSS_COMMENT.sub("", _style())


def _root_block() -> str:
    """The body of the :root rule, which must be the stylesheet's only :root and its first rule."""
    css = _css().strip()
    assert css.startswith(":root {"), "the token block must be the first rule"
    assert css.count(":root") == 1, "there must be one token block"
    return css[len(":root {") : css.index("}")]


def _rules_after_root() -> str:
    css = _css().strip()
    return css[css.index("}") + 1 :]


def _tokens() -> dict[str, str]:
    return {name: value.strip() for name, value in TOKEN.findall(_root_block())}


def _colour(name: str) -> str:
    """A token's colour as lower-case #rrggbb, following var() references."""
    value = _tokens()[name]
    reference = VAR_REFERENCE.fullmatch(value)
    if reference:
        return _colour(reference.group(1))
    assert re.fullmatch(r"#[0-9a-fA-F]{6}", value), f"{name} is not a #rrggbb colour: {value}"
    return value.lower()


def _channels(colour: str) -> list[int]:
    return [int(colour[index : index + 2], 16) for index in (1, 3, 5)]


def _mix(a: str, b: str, p: float) -> str:
    """p × a + (1 − p) × b per sRGB channel, rounded, as #rrggbb."""
    mixed = [round(p * x + (1 - p) * y) for x, y in zip(_channels(a), _channels(b))]
    return "#" + "".join(f"{channel:02x}" for channel in mixed)


def _luminance(colour: str) -> float:
    def linear(channel: int) -> float:
        value = channel / 255
        return value / 12.92 if value <= 0.03928 else ((value + 0.055) / 1.055) ** 2.4

    red, green, blue = (linear(channel) for channel in _channels(colour))
    return 0.2126 * red + 0.7152 * green + 0.0722 * blue


def _contrast(foreground: str, background: str) -> float:
    """The WCAG 2.1 contrast ratio of two #rrggbb colours."""
    lighter, darker = sorted((_luminance(foreground), _luminance(background)), reverse=True)
    return (lighter + 0.05) / (darker + 0.05)


def _declaration_values(css: str) -> list[str]:
    """The value of every declaration in every rule body (not selectors, not @media conditions)."""
    values = []
    for body in re.findall(r"\{([^{}]*)\}", css):
        for declaration in body.split(";"):
            if ":" in declaration:
                values.append(declaration.split(":", 1)[1].strip())
    return values


def _rules() -> list[tuple[str, list[str], str]]:
    """Every rule after the token block as (media condition or "", selectors, declarations)."""
    css = _rules_after_root()
    found = []
    for media in MEDIA_BLOCK.finditer(css):
        for selectors, body in RULE.findall(media.group(2)):
            found.append((media.group(1).strip(), [s.strip() for s in selectors.split(",")], body))
    for selectors, body in RULE.findall(MEDIA_BLOCK.sub("", css)):
        found.append(("", [s.strip() for s in selectors.split(",")], body))
    return found


def _rule(selector: str, media: str = "") -> str:
    """The declarations of every rule whose selector list holds exactly `selector`, joined."""
    bodies = [" ".join(body.split()) for condition, selectors, body in _rules() if condition == media and selector in selectors]
    assert bodies, f"no rule for {selector} {media}".strip()
    return "; ".join(bodies)


def _markup() -> str:
    """The page without its <style> block."""
    return STYLE_BLOCK.sub("", PAGE_HTML)


def _rem_to_px(value: str) -> float:
    assert value.endswith("rem"), value
    return float(value.removesuffix("rem")) * ROOT_FONT_PX


def test_brand_tokens_match_the_guide() -> None:
    tokens = _tokens()
    for name, value in BRAND_COLOURS.items():
        assert tokens[name].lower() == value.lower(), name


@pytest.mark.parametrize("name,first,second,share", DERIVED_COLOURS)
def test_derived_tokens_follow_the_formula(name: str, first: str, second: str, share: float) -> None:
    assert _colour(name) == _mix(_colour(first), _colour(second), share)


def test_styles_use_tokens_only() -> None:
    rules = _rules_after_root()

    assert not HEX_COLOUR.search(rules)
    assert not re.search(r"\b(rgba?|hsla?)\(", rules)
    values = _declaration_values(rules)
    assert len(values) > 60, "the declaration parser found too few declarations"
    for value in values:
        literal = VAR_REFERENCE.sub("", value)
        assert '"' not in literal, f"string in: {value}"
        numbers = re.findall(r"\d*\.?\d+(?:[a-z%]+)?", literal)
        assert all(number in ("0", "100%") for number in numbers), f"magic value in: {value}"
        words = set(re.findall(r"[A-Za-z][\w-]*", literal))
        assert words <= ALLOWED_VALUE_WORDS, f"literal {sorted(words - ALLOWED_VALUE_WORDS)} in: {value}"
    for match in re.finditer(r"font-family:\s*([^;}]+)", rules):
        assert re.fullmatch(r"var\(--font-[\w-]+\)", match.group(1).strip()), match.group(0)
    assert not re.search(r"(?<![\w-])font:", rules)
    markup = _markup()
    for forbidden in ('fill=', 'stroke=', "style=", "color=", "<style", "onclick"):
        assert forbidden not in markup, forbidden
    for svg in re.findall(r"<svg\b.*?</svg>", markup, re.S):
        for name, _ in re.findall(r'([\w:-]+)="([^"]*)"', svg):
            assert name in SVG_ATTRIBUTES, f"SVG attribute {name}"


def test_token_block_holds_only_tokens() -> None:
    assert _root_block().strip().endswith(";"), "every token ends with a semicolon"
    for declaration in _root_block().split(";"):
        if not declaration.strip():
            continue
        name, value = (part.strip() for part in declaration.split(":", 1))
        if name == "color-scheme":
            assert value == "light"
            continue
        assert name.startswith("--"), f"{name} in the token block"
        if name.startswith("--font-") and not name.startswith("--font-size"):
            assert FONT_STACK.fullmatch(value), f"{name}: {value}"
        elif name.startswith("--glyph-"):
            assert GLYPH_TOKEN.fullmatch(value), f"{name}: {value}"
        else:
            assert TOKEN_VALUE.fullmatch(value), f"{name}: {value}"


def test_tokens_are_defined_once() -> None:
    definitions = TOKEN.findall(_root_block())
    names = [name for name, _ in definitions]
    assert len(names) == len(set(names))

    literals = [value.strip() for _, value in definitions if not VAR_REFERENCE.fullmatch(value.strip())]
    colours = [value.lower() for value in literals if HEX_COLOUR.fullmatch(value)]
    assert len(colours) == len(set(colours))
    stacks = [value for value in literals if "," in value]
    assert len(stacks) == len(set(stacks))
    by_value: dict[str, set[str]] = {}
    for name, value in definitions:
        if not VAR_REFERENCE.fullmatch(value.strip()):
            by_value.setdefault(value.strip(), set()).add(name)
    shared = {value: names for value, names in by_value.items() if len(names) > 1}
    assert shared == SHARED_LITERALS, shared
    steps = [_rem_to_px(value.strip()) for name, value in definitions if re.fullmatch(r"--space-\d+", name)]
    assert steps == sorted(set(steps)) and len(steps) >= 6


def test_every_token_is_used() -> None:
    used = set(VAR_REFERENCE.findall(_css()))

    unused = set(_tokens()) - used
    assert unused == set(RESERVED_TOKENS), f"unused tokens: {sorted(unused - set(RESERVED_TOKENS))}"


def test_every_token_used_is_defined() -> None:
    used = set(VAR_REFERENCE.findall(_css()))

    assert used
    assert used <= set(_tokens())


def test_page_has_no_pure_white_black_or_old_colours() -> None:
    old = ("#fff", "#000", "#27ae60", "#229954", "#2980b9", "#e8ecef", "#c0392b", "#e74c3c", "#fbeae5", "#333", "#555")
    for name, page in _pages().items():
        for colour in old:
            assert colour not in page.lower(), (name, colour)
    assert not PURE_WHITE_OR_BLACK.search(_css())
    assert [name for name, value in _tokens().items() if value == "var(--asmbly-purple)"] == ["--logo-colour"]
    assert "var(--asmbly-purple)" not in _rules_after_root()


def test_ceramics_is_the_accent() -> None:
    tokens = _tokens()
    assert tokens["--accent"] == "var(--ceramics)"
    assert _colour("--accent-strong") == _colour("--ceramics-shade")
    assert _colour("--table-head-bg") == _colour("--ceramics-20")
    assert "background: var(--accent)" in _rule(".brand-band")
    assert "background: var(--accent-strong)" in _rule(".reload-button")
    assert "background: var(--table-head-bg)" in _rule("th")
    assert "color: var(--accent-strong)" in _rule(".task-id")


@pytest.mark.parametrize("foreground,background,minimum", CONTRAST_PAIRS)
def test_colour_pairs_meet_contrast(foreground: str, background: str, minimum: float) -> None:
    assert _contrast(_colour(foreground), _colour(background)) >= minimum


def test_band_text_is_large() -> None:
    """The band's h1 is large text at every width, so 3:1 is its minimum (README Decision 4)."""
    tokens = _tokens()
    assert _rem_to_px(tokens["--font-size-h1"]) >= 24
    assert int(tokens["--weight-heading"]) >= 700
    assert "font-size: var(--font-size-h1)" in _rule(".brand-band h1")
    assert "font-weight: var(--weight-heading)" in _rule("h1")
    for media, selectors, body in _rules():
        if media:
            assert not any("h1" in selector for selector in selectors), selectors
            assert "font-size" not in body, selectors


def test_headings_are_bold_and_larger_than_body() -> None:
    tokens = _tokens()
    body = _rem_to_px(tokens["--font-size-body"])
    assert _rem_to_px(tokens["--font-size-h2"]) >= 1.25 * body
    assert _rem_to_px(tokens["--font-size-h1"]) >= 1.25 * body
    assert int(tokens["--weight-heading"]) >= 700
    heading_rule = _rule("h2")
    assert "font-weight: var(--weight-heading)" in heading_rule
    assert "font-family: var(--font-heading)" in heading_rule


def test_drop_off_ids_are_bold_whole_and_at_least_body_size() -> None:
    """Members copy the ID onto a slip: it is bold, at least body size, and never split (#133)."""
    tokens = _tokens()
    rule = _rule(".task-id")
    assert "font-weight: var(--weight-heading)" in rule and int(tokens["--weight-heading"]) >= 700
    assert "font-size: var(--font-size-id)" in rule
    assert _rem_to_px(tokens["--font-size-id"]) >= _rem_to_px(tokens["--font-size-body"])
    assert "white-space: nowrap" in rule


def test_reload_button_is_a_44px_target_with_visible_focus() -> None:
    rule = _rule(".reload-button")
    assert "min-height: var(--tap-target)" in rule and "min-width: var(--tap-target)" in rule
    assert _rem_to_px(_tokens()["--tap-target"]) >= 44
    assert "outline: var(--focus-width) solid var(--focus)" in _rule(".reload-button:focus-visible")
    assert "outline-offset: var(--focus-offset)" in _rule(".reload-button:focus-visible")
    assert float(_tokens()["--focus-width"].removesuffix("px")) >= 2
    assert not re.search(r"outline:\s*(none|0)\b", _css())


def test_hover_only_where_hover_exists() -> None:
    assert [query.strip() for query in re.findall(r"@media([^{]*)\{", _css())] == [HOVER_MEDIA]
    assert "background: var(--row-hover-bg)" in _rule("tbody tr:hover", HOVER_MEDIA)
    assert "background: var(--accent-hover)" in _rule(".reload-button:hover", HOVER_MEDIA)
    assert not [selectors for media, selectors, _ in _rules() if media != HOVER_MEDIA and any(":hover" in s for s in selectors)]


def test_table_text_wraps_and_page_does_not_scroll_sideways() -> None:
    # A cell's text wraps anywhere, so no name widens the page.
    assert "overflow-wrap: anywhere" in _rule("td")
    # Headers wrap between words, so "Submitted" keeps the time column wide enough for the
    # date in the small size; the time ("2024-01-01 00:00:00") wraps only at its space.
    assert "overflow-wrap" not in _rule("th")
    time = _rule("td:nth-child(3)")
    assert "overflow-wrap: normal" in time and "font-size: var(--font-size-small)" in time
    nowrap = [selectors for _, selectors, body in _rules() if "white-space: nowrap" in body]
    assert nowrap == [[".task-id"]]
    widths = set(re.findall(r"(?<![\w-])width:\s*([^;]+);", _rules_after_root()))
    assert widths <= {"100%", "auto"}, widths
    assert "width: 100%" in _rule("table")
    assert not re.search(r"overflow(-x)?:\s*hidden", _css())
    assert "max-width: 100%" in _rule(".logo")


def test_error_box_differs_beyond_colour() -> None:
    assert "border-left: var(--border-width-accent) solid var(--error-edge)" in _rule(".error-box")
    assert "background: var(--error-bg)" in _rule(".error-box") and "color: var(--text)" in _rule(".error-box")
    glyph = _rule(".error-box h2::before")
    assert "content: var(--glyph-error)" in glyph and "color: var(--error-edge)" in glyph
    assert GLYPH_TOKEN.fullmatch(_tokens()["--glyph-error"])


def test_icon_and_logo_are_tokens_and_meet_the_logo_minimum() -> None:
    """The icon and logo take their colour from the text colour; the logo is at least 50px tall."""
    icon = _rule(".ceramics-icon")
    assert "height: var(--icon-height)" in icon and "fill: currentColor" in icon
    assert "height: var(--logo-height)" in _rule(".logo")
    assert _rem_to_px(_tokens()["--logo-height"]) >= 50
