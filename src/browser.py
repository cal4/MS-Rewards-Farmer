import argparse
import logging
import random
from pathlib import Path
from types import TracebackType
from typing import Any, Type

import ipapi
import seleniumwire.undetected_chromedriver as webdriver
import undetected_chromedriver
from ipapi.exceptions import RateLimited
from selenium.webdriver import ChromeOptions
from selenium.webdriver.chrome.webdriver import WebDriver

from src import Account
from src.userAgentGenerator import GenerateUserAgent
from src.utils import Utils


class Browser:
    """WebDriver wrapper class."""

    webdriver: undetected_chromedriver.Chrome

    def __init__(
        self, mobile: bool, account: Account, args: argparse.Namespace
    ) -> None:
        # Initialize browser instance
        logging.debug("in __init__")
        self.mobile = mobile
        self.browserType = "mobile" if mobile else "desktop"
        self.headless = not args.visible
        self.username = account.username
        self.password = account.password
        self.localeLang, self.localeGeo = self.getCCodeLang(args.lang, args.geo)
        self.proxy = None
        if args.proxy:
            self.proxy = args.proxy
        elif account.proxy:
            self.proxy = account.proxy
        self.userDataDir = self.setupProfiles()
        self.browserConfig = Utils.getBrowserConfig(self.userDataDir)
        (
            self.userAgent,
            self.userAgentMetadata,
            newBrowserConfig,
        ) = GenerateUserAgent().userAgent(self.browserConfig, mobile)
        if newBrowserConfig:
            self.browserConfig = newBrowserConfig
            Utils.saveBrowserConfig(self.userDataDir, self.browserConfig)
        self.webdriver = self.browserSetup()
        self.utils = Utils(self.webdriver)
        logging.debug("out __init__")

    def __enter__(self) -> "Browser":
        logging.debug("in __enter__")
        return self

    def __exit__(
        self,
        exc_type: Type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        # Cleanup actions when exiting the browser context
        logging.debug(
            f"in __exit__ exc_type={exc_type} exc_value={exc_value} traceback={traceback}"
        )
        # turns out close is needed for undetected_chromedriver
        self.webdriver.close()
        self.webdriver.quit()

    def browserSetup(
        self,
    ) -> undetected_chromedriver.Chrome:
        # Configure and setup the Chrome browser
        options = undetected_chromedriver.ChromeOptions()
        options.headless = self.headless
        options.add_argument(f"--lang={self.localeLang}")
        options.add_argument("--log-level=3")
        options.add_argument("--blink-settings=imagesEnabled=false")
        options.add_argument("--ignore-certificate-errors")
        options.add_argument("--ignore-certificate-errors-spki-list")
        options.add_argument("--ignore-ssl-errors")
        options.add_argument("--no-sandbox")
        options.add_argument("--disable-extensions")
        options.add_argument("--dns-prefetch-disable")
        options.add_argument("--disable-gpu")
        options.add_argument("--disable-default-apps")
        options.add_argument("--disable-features=Translate")
        options.add_argument("--disable-features=PrivacySandboxSettings4")

        seleniumwireOptions: dict[str, Any] = {"verify_ssl": False}

        if self.proxy:
            # Setup proxy if provided
            seleniumwireOptions["proxy"] = {
                "http": self.proxy,
                "https": self.proxy,
                "no_proxy": "localhost,127.0.0.1",
            }

        # Obtain webdriver chrome driver version
        version = self.getChromeVersion()
        major = int(version.split(".")[0])

        driver = webdriver.Chrome(
            options=options,
            seleniumwire_options=seleniumwireOptions,
            user_data_dir=self.userDataDir.as_posix(),
            version_main=major,
        )

        seleniumLogger = logging.getLogger("seleniumwire")
        seleniumLogger.setLevel(logging.ERROR)

        if self.browserConfig.get("sizes"):
            deviceHeight = self.browserConfig["sizes"]["height"]
            deviceWidth = self.browserConfig["sizes"]["width"]
        else:
            if self.mobile:
                deviceHeight = random.randint(568, 1024)
                deviceWidth = random.randint(320, min(576, int(deviceHeight * 0.7)))
            else:
                deviceWidth = random.randint(1024, 2560)
                deviceHeight = random.randint(768, min(1440, int(deviceWidth * 0.8)))
            self.browserConfig["sizes"] = {
                "height": deviceHeight,
                "width": deviceWidth,
            }
            Utils.saveBrowserConfig(self.userDataDir, self.browserConfig)

        if self.mobile:
            screenHeight = deviceHeight + 146
            screenWidth = deviceWidth
        else:
            screenWidth = deviceWidth + 55
            screenHeight = deviceHeight + 151

        logging.info(f"Screen size: {screenWidth}x{screenHeight}")
        logging.info(f"Device size: {deviceWidth}x{deviceHeight}")

        if self.mobile:
            driver.execute_cdp_cmd(
                "Emulation.setTouchEmulationEnabled",
                {
                    "enabled": True,
                },
            )

        driver.execute_cdp_cmd(
            "Emulation.setDeviceMetricsOverride",
            {
                "width": deviceWidth,
                "height": deviceHeight,
                "deviceScaleFactor": 0,
                "mobile": self.mobile,
                "screenWidth": screenWidth,
                "screenHeight": screenHeight,
                "positionX": 0,
                "positionY": 0,
                "viewport": {
                    "x": 0,
                    "y": 0,
                    "width": deviceWidth,
                    "height": deviceHeight,
                    "scale": 1,
                },
            },
        )

        driver.execute_cdp_cmd(
            "Emulation.setUserAgentOverride",
            {
                "userAgent": self.userAgent,
                "platform": self.userAgentMetadata["platform"],
                "userAgentMetadata": self.userAgentMetadata,
            },
        )

        return driver

    def setupProfiles(self) -> Path:
        """
        Sets up the sessions profile for the chrome browser.
        Uses the username to create a unique profile for the session.

        Returns:
            Path
        """
        sessionsDir = Utils.getProjectRoot() / "sessions"

        # Concatenate username and browser type for a plain text session ID
        sessionid = f"{self.username}"

        sessionsDir = sessionsDir / sessionid
        sessionsDir.mkdir(parents=True, exist_ok=True)
        return sessionsDir

    @staticmethod
    def getCCodeLang(lang: str, geo: str) -> tuple:
        if lang is None or geo is None:
            try:
                nfo = ipapi.location()
            except RateLimited:
                logging.warning("Returning default", exc_info=True)
                return "en", "US"
            if isinstance(nfo, dict):
                if lang is None:
                    lang = nfo["languages"].split(",")[0].split("-")[0]
                if geo is None:
                    geo = nfo["country"]
        return lang, geo

    @staticmethod
    def getChromeVersion() -> str:
        chrome_options = ChromeOptions()
        chrome_options.add_argument("--headless=new")

        driver = WebDriver(options=chrome_options)
        version = driver.capabilities["browserVersion"]

        driver.quit()

        return version
