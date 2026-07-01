# Automate-Pulse-Pro-for-Home-Assistant
Add blinds that connect to the Automate Pulse Pro

Make sure to add your blinds to the Automate app first. If you need to add another blind simply add it to your app and reload the integration.

Add the IP adddress of your Pulse Pro and add 1487 as the PORT number

Battery level is also exposed!

Disclaimer. This has been vibe coded using Gemini. Hopefully someone can take it and run with it to improve and make the code more efficient


***** Installation Guide

* Step 1: Prerequisites
You must have HACS installed.

* Step 2: Install via HACS

Open HACS -> Integrations.
Click the menu (three dots) in the top right -> Custom repositories.
Paste this repository URL: https://github.com/IamDan77/Automate-Pulse-Pro-for-Home-Assistant
Select Category: Integration.
Click Add, then find Automate-Pulse-Pro in the list and install it.
Restart Home Assistant.
Step 3: Install Manually (Alternative)

Download this repository.
Copy the custom_components/automate-pulse-pro folder into your config/custom_components/ directory.
Restart Home Assistant.
