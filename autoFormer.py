import argparse
import random
import time

from selenium import webdriver
from selenium.common.exceptions import TimeoutException
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait
from webdriver_manager.chrome import ChromeDriverManager


DEFAULT_FORM_LINK = (
    "https://docs.google.com/forms/d/e/"
    "1FAIpQLSfzU6012o4udN1SzFK5wdV5cXHIpw19c2MPWKzmVKWgNTOrSA/"
    "viewform?usp=publish-editor"
)

MAX_RESPONSES_PER_RUN = 20

SAMPLE_VALUES = {
    "names": ["ram", "balaji", "satish", "sandesh", "vivek", "vishnu", "vaibhav", "amol"],
    "departments": [
        "CSE (Computer Science Engineering)",
        "CSD",
        "Civil Engineering",
        "Other",
    ],
    "years": ["1st Year", "2nd Year", "3rd Year", "Final Year"],
    "emails": ["test@example.com"],
    "phones": ["1234567890"],
    "suggestions": [
        "Improve digital learning with AI tools",
        "More hands-on training would help",
        "Provide better support for online classes",
        "Increase interactivity in the course",
    ],
}


def parse_args():
    parser = argparse.ArgumentParser(
        description="Fill Google Form responses with sample or detected values."
    )
    parser.add_argument(
        "url",
        nargs="?",
        help="Google Form URL. If omitted, you will be prompted.",
    )
    parser.add_argument(
        "--no-submit",
        action="store_true",
        help="Fill the form but leave it open without clicking Submit.",
    )
    parser.add_argument(
        "--responses",
        type=int,
        default=None,
        help=(
            "Number of responses to submit in this run. "
            f"If omitted, you will be prompted. Max: {MAX_RESPONSES_PER_RUN}."
        ),
    )
    parser.add_argument(
        "--delay",
        type=float,
        default=2.0,
        help="Seconds to wait between submitted responses.",
    )
    parser.add_argument(
        "--i-have-permission",
        action="store_true",
        help="Confirm you own the form or have permission to submit multiple responses.",
    )
    parser.add_argument(
        "--headless",
        action="store_true",
        help="Run Chrome without opening a visible browser window.",
    )
    parser.add_argument(
        "--keep-open",
        action="store_true",
        help="Wait before closing Chrome so you can inspect the filled form.",
    )
    args = parser.parse_args()

    if args.responses is not None:
        if args.responses < 1:
            parser.error("--responses must be at least 1")
        if args.responses > MAX_RESPONSES_PER_RUN:
            parser.error(f"--responses cannot be more than {MAX_RESPONSES_PER_RUN} per run")
    if args.delay < 0:
        parser.error("--delay cannot be negative")
    if args.no_submit and args.responses and args.responses > 1:
        parser.error("--no-submit can only be used with --responses 1")
    if args.responses and args.responses > 1 and not args.i_have_permission:
        parser.error(
            "--responses greater than 1 requires --i-have-permission. "
            "Use this only for forms you own or have permission to test."
        )

    return args


def ask_response_count(no_submit=False):
    while True:
        raw_value = input(
            f"How many responses do you want to submit? (1-{MAX_RESPONSES_PER_RUN}, default 1): "
        ).strip()
        if not raw_value:
            response_count = 1
        else:
            try:
                response_count = int(raw_value)
            except ValueError:
                print("Please enter a number.")
                continue

        if response_count < 1:
            print("Please enter at least 1.")
            continue
        if response_count > MAX_RESPONSES_PER_RUN:
            print(f"Please enter {MAX_RESPONSES_PER_RUN} or less.")
            continue
        if no_submit and response_count > 1:
            print("--no-submit can only be used with 1 response.")
            continue

        return response_count


def confirm_multiple_responses(response_count, already_confirmed):
    if response_count <= 1 or already_confirmed:
        return True

    answer = input(
        "Do you own this form or have permission to submit multiple responses? "
        "Type YES to continue: "
    ).strip()
    return answer == "YES"


def normalize_text(text):
    return (
        text.strip()
        .lower()
        .replace("\u2013", "-")
        .replace("\u2014", "-")
    )


def scroll_to(driver, element):
    driver.execute_script(
        "arguments[0].scrollIntoView({block: 'center', inline: 'nearest'});",
        element,
    )
    time.sleep(0.15)


def click_element(driver, element):
    scroll_to(driver, element)
    try:
        element.click()
    except Exception:
        driver.execute_script("arguments[0].click();", element)


def get_questions(driver, wait):
    wait.until(EC.presence_of_element_located((By.XPATH, '//div[@role="listitem"]')))
    return driver.find_elements(By.XPATH, '//div[@role="listitem"]')


def get_question_text(question):
    headings = question.find_elements(By.XPATH, './/*[@role="heading"]')
    for heading in headings:
        text = heading.text.strip()
        if text:
            return text.replace(" *", "").strip()

    lines = [line.strip() for line in question.text.splitlines() if line.strip()]
    return lines[0].replace(" *", "").strip() if lines else "Untitled question"


def get_question_type(question):
    if question.find_elements(By.XPATH, './/div[@role="checkbox"]'):
        return "checkbox"
    if question.find_elements(By.XPATH, './/div[@role="radio"]'):
        return "radio"
    if question.find_elements(By.XPATH, ".//textarea"):
        return "textarea"
    if question.find_elements(By.XPATH, './/input[@type="text" or not(@type)]'):
        return "text"
    return "unknown"


def option_elements(question, qtype):
    role = "checkbox" if qtype == "checkbox" else "radio"
    return question.find_elements(By.XPATH, f'.//div[@role="{role}"]')


def option_text(option):
    aria_label = option.get_attribute("aria-label")
    if aria_label:
        return aria_label.strip()

    text = option.text.strip()
    if text:
        return text

    labelledby = option.get_attribute("aria-labelledby")
    if labelledby:
        return labelledby.strip()

    return ""


def get_options(question, qtype):
    if qtype not in {"radio", "checkbox"}:
        return []

    options = []
    for element in option_elements(question, qtype):
        text = option_text(element)
        if text and text not in options:
            options.append(text)
    return options


def answer_for_text_question(question_text):
    text = normalize_text(question_text)

    if "name" in text:
        return random.choice(SAMPLE_VALUES["names"])
    if "email" in text:
        return random.choice(SAMPLE_VALUES["emails"])
    if "phone" in text or "mobile" in text or "contact" in text:
        return random.choice(SAMPLE_VALUES["phones"])
    if "department" in text or "branch" in text:
        return random.choice(SAMPLE_VALUES["departments"])
    if "year" in text:
        return random.choice(SAMPLE_VALUES["years"])
    if "sgpa" in text or "cgpa" in text or "gpa" in text:
        return f"{random.uniform(6.0, 10.0):.2f}"
    if "suggest" in text or "feedback" in text or "comment" in text:
        return random.choice(SAMPLE_VALUES["suggestions"])

    return "Test Answer"


def choose_answer(question_text, qtype, options):
    print(f"\nQuestion: {question_text}")
    print(f"Type: {qtype}")

    if options:
        print("Options:")
        for number, option in enumerate(options, 1):
            print(f"  {number}. {option}")

    if qtype in {"text", "textarea", "unknown"} or not options:
        answer = answer_for_text_question(question_text)
    elif qtype == "checkbox":
        answer_count = random.randint(1, min(2, len(options)))
        answer = random.sample(options, k=answer_count)
    else:
        answer = random.choice(options)

    print(f"Answer: {answer}")
    return answer


def fill_text(question, answer):
    fields = question.find_elements(By.XPATH, ".//textarea")
    if not fields:
        fields = question.find_elements(By.XPATH, './/input[@type="text" or not(@type)]')
    if not fields:
        raise RuntimeError("No text field found")

    field = fields[0]
    field.click()
    field.send_keys(Keys.CONTROL, "a")
    field.send_keys(answer)


def select_options(driver, question, qtype, answers):
    wanted = {normalize_text(answer) for answer in answers}

    for element in option_elements(question, qtype):
        text = option_text(element)
        if normalize_text(text) in wanted:
            click_element(driver, element)
            wanted.remove(normalize_text(text))

    if wanted:
        missing = ", ".join(sorted(wanted))
        raise RuntimeError(f"Could not find option(s): {missing}")


def fill_question(driver, question):
    question_text = get_question_text(question)
    qtype = get_question_type(question)
    options = get_options(question, qtype)
    answer = choose_answer(question_text, qtype, options)

    if qtype in {"text", "textarea", "unknown"}:
        fill_text(question, answer)
    elif qtype == "checkbox":
        select_options(driver, question, qtype, answer)
    elif qtype == "radio":
        select_options(driver, question, qtype, [answer])


def setup_browser(headless=False):
    options = webdriver.ChromeOptions()
    options.add_argument("--incognito")
    options.add_argument("--disable-notifications")
    if headless:
        options.add_argument("--headless=new")
        options.add_argument("--disable-gpu")

    service = Service(ChromeDriverManager().install())
    return webdriver.Chrome(service=service, options=options)


def submit_form(driver, wait):
    submit = wait.until(
        EC.element_to_be_clickable(
            (
                By.XPATH,
                '//div[@role="button"][.//span[normalize-space()="Submit"]]',
            )
        )
    )
    click_element(driver, submit)


def fill_form_once(browser, wait, form_link, response_number, total_responses):
    print(f"\n=== Response {response_number} of {total_responses} ===")
    browser.get(form_link)
    questions = get_questions(browser, wait)
    print(f"\nFound {len(questions)} questions.")

    failed_questions = 0
    for index, question in enumerate(questions, 1):
        try:
            fill_question(browser, question)
        except Exception as exc:
            failed_questions += 1
            print(f"Failed to fill question {index}: {exc}")

    return failed_questions


def main():
    args = parse_args()
    form_link = args.url
    if not form_link:
        form_link = input("Enter Google Form URL (press Enter to use the default form): ").strip()
    if not form_link:
        form_link = DEFAULT_FORM_LINK

    if args.responses is None:
        args.responses = ask_response_count(no_submit=args.no_submit)

    if not confirm_multiple_responses(args.responses, args.i_have_permission):
        print("Stopped. Multiple responses require permission from the form owner.")
        return

    browser = setup_browser(headless=args.headless)
    wait = WebDriverWait(browser, 20)

    try:
        submitted = 0
        for response_number in range(1, args.responses + 1):
            failed_questions = fill_form_once(
                browser,
                wait,
                form_link,
                response_number,
                args.responses,
            )

            if args.no_submit:
                print("\nFilled form. Submit skipped because --no-submit was used.")
                break

            if failed_questions:
                print(
                    f"\nSkipped submit for response {response_number} because "
                    f"{failed_questions} question(s) failed."
                )
                continue

            submit_form(browser, wait)
            submitted += 1
            print(f"\nSubmitted response {response_number}.")

            if response_number < args.responses:
                time.sleep(args.delay)

        if not args.no_submit:
            print(f"\nFinished. Submitted {submitted} of {args.responses} responses.")

        if args.keep_open:
            input("Press Enter to close Chrome...")
    except TimeoutException:
        print("Timed out waiting for the Google Form to load.")
    finally:
        browser.quit()


if __name__ == "__main__":
    main()
