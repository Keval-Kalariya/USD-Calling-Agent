import json
import os

# Get the path to data/covered_cities.json
DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "data")
CITIES_FILE = os.path.join(DATA_DIR, "covered_cities.json")

def check_city_coverage(city: str) -> dict:
    """
    Check if Ultimate Smile Design covers a specific city.
    
    Args:
        city (str): The name of the city to check.
        
    Returns:
        dict: A dictionary containing the coverage result string.
    """
    if not os.path.exists(CITIES_FILE):
        return {"result": f"Coverage Not Found for {city} (Database unavailable)"}
        
    try:
        with open(CITIES_FILE, "r", encoding="utf-8") as f:
            covered_cities = json.load(f)
            
        # Case-insensitive comparison
        city_lower = city.strip().lower()
        is_covered = any(c.lower() == city_lower for c in covered_cities)
        
        if is_covered:
            return {"result": f"Coverage Confirmed for {city}"}
        else:
            return {"result": f"Coverage Not Found for {city}"}
            
    except Exception as e:
        return {"result": f"Coverage Not Found for {city} (Error: {str(e)})"}
