#!/usr/bin/env bash
set -e
cd "$(dirname "$0")"

after_action() {
    echo
    echo "Task finished. Exit code: $?"
    read -rp "Press Enter to return to the launcher menu..."
    echo
}

while true; do
    echo "=========================================="
    echo " Parser Agent launcher"
    echo "=========================================="
    echo
    echo "  1. Start Telegram bot"
    echo "  2. Update prices once"
    echo "  3. Show last parsing metrics"
    echo "  4. Run tests"
    echo "  5. Install/update dependencies"
    echo "  6. Open Ozon browser profile"
    echo "  7. Generate HTML report"
    echo "  8. Deploy WB Cloud Function"
    echo "  0. Exit"
    echo

    read -rp "Choose action: " choice

    case "$choice" in
        1)
            echo "Starting Telegram bot..."
            python3 -m app.main --telegram
            after_action
            ;;
        2)
            echo "Updating prices once..."
            python3 -m app.main --update
            after_action
            ;;
        3)
            echo "Showing last parsing metrics..."
            python3 -m app.main --metrics 20
            after_action
            ;;
        4)
            echo "Running tests..."
            .venv/bin/python -m unittest discover -s tests -v
            after_action
            ;;
        5)
            echo "Installing Python dependencies..."
            python3 -m pip install -r requirements.txt
            echo "Installing Playwright Chromium..."
            python3 -m playwright install chromium
            after_action
            ;;
        6)
            echo "Opening visible Ozon browser profile (manual login/captcha warm-up)..."
            python3 -m app.main --ozon-login
            after_action
            ;;
        7)
            echo "Generating HTML report with embedded images..."
            python3 -m app.main --report --embed-images
            after_action
            ;;
        8)
            echo "Deploying WB Cloud Function to Yandex Cloud..."
            python3 -m app.main --deploy-wb
            after_action
            ;;
        0)
            echo "Bye!"
            exit 0
            ;;
        *)
            echo "Unknown choice."
            after_action
            ;;
    esac
done
