#!/usr/bin/python3
import urllib.request
import urllib.error


def checkInternetConnectivity():
    try:
        urllib.request.urlopen("http://google.com", timeout=2)
        print("Working connection")

    except urllib.error.URLError as E:
        print("Connection error:%s" % E.reason)


checkInternetConnectivity()
