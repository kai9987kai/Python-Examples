#!/usr/bin/python3
"""
Description : Fetches current weather information for a user-specified city using the free 
              Open-Meteo API (requires only standard libraries: urllib and json).
Author      : Antigravity
"""
import urllib.request
import urllib.parse
import json
import sys

# Try to reconfigure stdout/stderr to support UTF-8 (emojis) on Windows consoles
try:
    sys.stdout.reconfigure(encoding='utf-8')
    sys.stderr.reconfigure(encoding='utf-8')
except Exception:
    pass

# Handle Python 2/3 compatibility for input
try:
    input = raw_input
except NameError:
    pass

# Open-Meteo WMO Weather interpretation codes (WMOCodes)
WEATHER_CODES = {
    0: "Clear sky ☀️",
    1: "Mainly clear 🌤️",
    2: "Partly cloudy ⛅",
    3: "Overcast ☁️",
    45: "Fog 🌫️",
    48: "Depositing rime fog 🌫️",
    51: "Light drizzle 🌧️",
    53: "Moderate drizzle 🌧️",
    55: "Dense drizzle 🌧️",
    56: "Light freezing drizzle 🌧️❄️",
    57: "Dense freezing drizzle 🌧️❄️",
    61: "Slight rain 🌧️",
    63: "Moderate rain 🌧️",
    65: "Heavy rain 🌧️🌧️",
    66: "Light freezing rain 🌧️❄️",
    67: "Heavy freezing rain 🌧️❄️",
    71: "Slight snow fall ❄️",
    73: "Moderate snow fall ❄️",
    75: "Heavy snow fall ❄️❄️",
    77: "Snow grains ❄️",
    80: "Slight rain showers 🌦️",
    81: "Moderate rain showers 🌦️",
    82: "Violent rain showers ⛈️",
    85: "Slight snow showers 🌨️",
    86: "Heavy snow showers 🌨️",
    95: "Thunderstorm 🌩️",
    96: "Thunderstorm with slight hail 🌩️🌨️",
    99: "Thunderstorm with heavy hail 🌩️🌨️"
}


def fetch_json(url):
    """Utility function to fetch and parse JSON from a URL."""
    headers = {"User-Agent": "WeatherFetcherExample/1.0 (Python Weather Script)"}
    req = urllib.request.Request(url, headers=headers)
    
    with urllib.request.urlopen(req) as response:
        if response.status == 200:
            return json.loads(response.read().decode('utf-8'))
        else:
            raise Exception(f"HTTP Error: {response.status}")


def geocode_city(city_name):
    """Resolves city name to latitude, longitude, and country info using Open-Meteo Geocoding API."""
    encoded_city = urllib.parse.quote(city_name)
    url = f"https://geocoding-api.open-meteo.com/v1/search?name={encoded_city}&count=1&language=en&format=json"
    
    data = fetch_json(url)
    
    if "results" not in data or not data["results"]:
        return None
        
    result = data["results"][0]
    return {
        "name": result.get("name"),
        "country": result.get("country"),
        "admin1": result.get("admin1"),  # State/Province
        "latitude": result.get("latitude"),
        "longitude": result.get("longitude")
    }


def fetch_weather(lat, lon):
    """Fetches current weather for given coordinates."""
    url = f"https://api.open-meteo.com/v1/forecast?latitude={lat}&longitude={lon}&current_weather=true"
    data = fetch_json(url)
    
    if "current_weather" not in data:
        raise Exception("Failed to retrieve weather data.")
        
    return data["current_weather"]


def main():
    print("=========================================")
    print("       COMMAND-LINE WEATHER VIEWER       ")
    print("=========================================")
    
    city_name = input("Enter city name (e.g. London, Tokyo): ").strip()
    if not city_name:
        print("Please enter a valid city name.")
        sys.exit(1)
        
    print(f"\nSearching for '{city_name}'...")
    try:
        location = geocode_city(city_name)
        if not location:
            print(f"Error: Could not find coordinates for city '{city_name}'.")
            sys.exit(1)
            
        loc_str = location['name']
        if location['admin1']:
            loc_str += f", {location['admin1']}"
        if location['country']:
            loc_str += f", {location['country']}"
            
        print(f"Found: {loc_str}")
        print(f"Coordinates: Lat: {location['latitude']}, Lon: {location['longitude']}")
        print("Fetching current weather...")
        
        weather = fetch_weather(location['latitude'], location['longitude'])
        
        temp = weather.get("temperature")
        windspeed = weather.get("windspeed")
        weather_code = weather.get("weathercode")
        time_fetched = weather.get("time")
        
        condition = WEATHER_CODES.get(weather_code, "Unknown weather condition")
        
        print("\n" + "=" * 41)
        print(f" Weather for: {location['name']}")
        print(f" Location:    {loc_str}")
        print("-" * 41)
        print(f" Temperature: {temp}°C")
        print(f" Condition:   {condition}")
        print(f" Wind Speed:  {windspeed} km/h")
        print(f" Time Local:  {time_fetched}")
        print("=" * 41)
        
    except Exception as e:
        print(f"\nError: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
