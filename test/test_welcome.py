import selenium.webdriver
import time
import os

#pylint:disable=unused-argument

from utils import PROTO, HOST, workspace_run
from selenium.webdriver.common.keys import Keys

def load_vscode_terminal(wd):
	wd.switch_to.new_window("tab")
	wd.get(f"{PROTO}://{HOST}/workspace/vscode/")
	time.sleep(1)
	wd.switch_to.active_element.send_keys(Keys.CONTROL + Keys.SHIFT + "`")
	time.sleep(1)

def start_chal(button, result):
	button.click()
	while "started" not in result.text:
		time.sleep(0.5)
	time.sleep(1)

def test_welcome(random_user, welcome_dojo):
	gd = "/snap/bin/geckodriver"
	if os.path.exists(gd):
		ds = selenium.webdriver.FirefoxService(executable_path=gd)
		wd = selenium.webdriver.Firefox(service=ds)
	else:
		wd = selenium.webdriver.Firefox()

	wd.get(f"{PROTO}://{HOST}/login")

	random_id,_ = random_user

	wd.find_element("id", "name").send_keys(random_id)
	wd.find_element("id", "password").send_keys(random_id)
	wd.find_element("id", "_submit").click()

	wd.get(f"{PROTO}://{HOST}/welcome/welcome")
	num_challenges = len(wd.find_elements("id", "challenge-start"))

	module_window = wd.current_window_handle

	for n in range(num_challenges):
		challenge_header = wd.find_element("id", f"challenges-header-button-{n+1}")
		challenge_name = challenge_header.text.split("\n")[0]
		challenge_header.click()
		time.sleep(0.5)

		challenge_body = wd.find_element("id", f"challenges-body-{n+1}")
		start = challenge_body.find_element("id", "challenge-start")
		practice = challenge_body.find_element("id", "challenge-practice")
		flagbox = challenge_body.find_element("id", "challenge-input")
		submit = challenge_body.find_element("id", "challenge-submit")
		result = challenge_body.find_element("id", "result-message")

		if   challenge_name == "Using the VSCode Workspace":
			start_chal(start, result)
			load_vscode_terminal(wd)
			wd.switch_to.active_element.send_keys("/challenge/solve | tee /tmp/out\n")
			time.sleep(5)
			# can't figure out how to get the output, so here we go
			flag = workspace_run("tail -n1 /tmp/out", user=random_id).stdout.split()[-1]
			wd.close()
			wd.switch_to.window(module_window)

			flagbox.send_keys(flag)
			submit.click()
			while "Correct" not in result.text:
				time.sleep(0.5)
		elif challenge_name == "Using the GUI Desktop":
			pass
		elif challenge_name == "Pasting into the Desktop":
			pass
		elif challenge_name == "The Flag File":
			pass
		elif challenge_name == "Using Practice Mode":
			start_chal(practice, result)
			load_vscode_terminal(wd)
			wd.switch_to.active_element.send_keys("sudo chmod 644 /challenge/secret\n")
			wd.switch_to.active_element.send_keys("cp /challenge/secret /home/hacker/\n")
			wd.close()
			wd.switch_to.window(module_window)

			start_chal(start, result)
			load_vscode_terminal(wd)
			wd.switch_to.active_element.send_keys("/challenge/solve < secret | tee /tmp/out\n")
			time.sleep(5)
			# can't figure out how to get the output, so here we go
			flag = workspace_run("tail -n1 /tmp/out", user=random_id).stdout.split()[-1]
			wd.close()
			wd.switch_to.window(module_window)

			flagbox.send_keys(flag)
			submit.click()
			while "Correct" not in result.text:
				time.sleep(0.5)
		elif challenge_name == "Persistent Home Directories - One":
			pass
		elif challenge_name == "Persistent Home Directories - Two":
			pass
		else:
			raise AssertionError(f"Unexpected challenge name: {challenge_header.text}")
