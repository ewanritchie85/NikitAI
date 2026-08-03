from unittest.mock import patch

from nikitai.cli import main


def test_main_importable():
    assert callable(main)


@patch("nikitai.agent.run_agent")
@patch("dotenv.load_dotenv")
def test_main_loads_dotenv_and_runs_agent(mock_load_dotenv, mock_run_agent):
    main()

    mock_load_dotenv.assert_called_once_with()
    mock_run_agent.assert_called_once_with()
