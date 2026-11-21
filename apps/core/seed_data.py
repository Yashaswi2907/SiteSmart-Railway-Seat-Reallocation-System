"""Fictional demonstration data. Train numbers, names and people are invented for the
academic project; station names are real places used only for geography."""
import datetime as dt

T = dt.time

STATIONS = [
    # code, name, city, state, zone
    ("NDLS", "New Delhi", "New Delhi", "Delhi", "Northern"),
    ("CNB", "Kanpur Central", "Kanpur", "Uttar Pradesh", "North Central"),
    ("LKO", "Lucknow Charbagh", "Lucknow", "Uttar Pradesh", "Northern"),
    ("BSB", "Varanasi Junction", "Varanasi", "Uttar Pradesh", "Northern"),
    ("ADI", "Ahmedabad Junction", "Ahmedabad", "Gujarat", "Western"),
    ("BRC", "Vadodara Junction", "Vadodara", "Gujarat", "Western"),
    ("ST", "Surat", "Surat", "Gujarat", "Western"),
    ("VAPI", "Vapi", "Vapi", "Gujarat", "Western"),
    ("MMCT", "Mumbai Central", "Mumbai", "Maharashtra", "Western"),
    ("CSMT", "Mumbai CSMT", "Mumbai", "Maharashtra", "Central"),
    ("PUNE", "Pune Junction", "Pune", "Maharashtra", "Central"),
    ("SUR", "Solapur", "Solapur", "Maharashtra", "Central"),
    ("SC", "Secunderabad Junction", "Hyderabad", "Telangana", "South Central"),
    ("GGN", "Gurugram", "Gurugram", "Haryana", "Northern"),
    ("RE", "Rewari", "Rewari", "Haryana", "North Western"),
    ("AWR", "Alwar", "Alwar", "Rajasthan", "North Western"),
    ("JP", "Jaipur Junction", "Jaipur", "Rajasthan", "North Western"),
    ("MAS", "Chennai Central", "Chennai", "Tamil Nadu", "Southern"),
    ("BZA", "Vijayawada Junction", "Vijayawada", "Andhra Pradesh", "South Central"),
    ("VSKP", "Visakhapatnam", "Visakhapatnam", "Andhra Pradesh", "East Coast"),
    ("BBS", "Bhubaneswar", "Bhubaneswar", "Odisha", "East Coast"),
    ("HWH", "Howrah Junction", "Kolkata", "West Bengal", "Eastern"),
    ("ASN", "Asansol Junction", "Asansol", "West Bengal", "Eastern"),
    ("GAYA", "Gaya Junction", "Gaya", "Bihar", "East Central"),
    ("DDU", "Pt. Deen Dayal Upadhyaya Jn", "Chandauli", "Uttar Pradesh", "East Central"),
    ("PRYJ", "Prayagraj Junction", "Prayagraj", "Uttar Pradesh", "North Central"),
    ("AGC", "Agra Cantt", "Agra", "Uttar Pradesh", "North Central"),
    ("GWL", "Gwalior Junction", "Gwalior", "Madhya Pradesh", "North Central"),
    ("BPL", "Bhopal Junction", "Bhopal", "Madhya Pradesh", "West Central"),
]

# number, name, type, running days, description, stops, coaches
# stop: (code, arrival, departure, day_offset, km)
TRAINS = [
    {
        "number": "24051", "name": "Kashi SmartSeat Express", "type": "SUPERFAST", "days": "1111111",
        "description": "Demonstration train for the no-show reallocation scenario.",
        "stops": [("NDLS", None, T(6, 0), 0, 0), ("CNB", T(11, 5), T(11, 15), 0, 440),
                  ("LKO", T(13, 25), T(13, 35), 0, 512), ("BSB", T(19, 10), None, 0, 818)],
        "coaches": [("S1", "SL"), ("S2", "SL"), ("B1", "3A"), ("A1", "2A")],
    },
    {
        "number": "22907", "name": "Western Corridor Superfast", "type": "SUPERFAST", "days": "1111111",
        "description": "Five-stop A→B→C→D→E corridor used for general segment demos.",
        "stops": [("ADI", None, T(5, 40), 0, 0), ("BRC", T(7, 25), T(7, 30), 0, 100), ("ST", T(9, 10), T(9, 15), 0, 229),
                  ("VAPI", T(10, 35), T(10, 37), 0, 325), ("MMCT", T(13, 5), None, 0, 492)],
        "coaches": [("C1", "CC"), ("C2", "CC"), ("D1", "2S")],
    },
    {
        "number": "12733", "name": "Deccan Link Express", "type": "EXPRESS", "days": "1010101",
        "description": "Tri-weekly link across the Deccan plateau.",
        "stops": [("CSMT", None, T(7, 10), 0, 0), ("PUNE", T(10, 20), T(10, 25), 0, 192),
                  ("SUR", T(14, 5), T(14, 10), 0, 455), ("SC", T(21, 30), None, 0, 772)],
        "coaches": [("S1", "SL"), ("S2", "SL"), ("B1", "3A")],
    },
    {
        "number": "19621", "name": "Pink City Intercity", "type": "INTERCITY", "days": "1111110",
        "description": "Day intercity with chair car and second sitting.",
        "stops": [("NDLS", None, T(7, 45), 0, 0), ("GGN", T(8, 20), T(8, 22), 0, 32), ("RE", T(9, 5), T(9, 7), 0, 83),
                  ("AWR", T(10, 5), T(10, 8), 0, 158), ("JP", T(12, 20), None, 0, 308)],
        "coaches": [("C1", "CC"), ("C2", "CC"), ("D1", "2S")],
    },
    {
        "number": "13511", "name": "Coromandel Coast Mail", "type": "MAIL", "days": "1111111",
        "description": "Overnight mail along the east coast.",
        "stops": [("MAS", None, T(21, 0), 0, 0), ("BZA", T(3, 40), T(3, 55), 1, 431),
                  ("VSKP", T(10, 15), T(10, 35), 1, 781), ("BBS", T(17, 20), T(17, 35), 1, 1224),
                  ("HWH", T(23, 55), None, 1, 1661)],
        "coaches": [("S1", "SL"), ("B1", "3A"), ("A1", "2A"), ("H1", "1A")],
    },
    {
        "number": "15019", "name": "Ganga Sagar Express", "type": "EXPRESS", "days": "1111101",
        "description": "Overnight service from Howrah to Kanpur via the Gangetic plain.",
        "stops": [("HWH", None, T(18, 10), 0, 0), ("ASN", T(21, 0), T(21, 5), 0, 200), ("GAYA", T(2, 10), T(2, 15), 1, 458),
                  ("DDU", T(5, 30), T(5, 45), 1, 661), ("PRYJ", T(8, 30), T(8, 35), 1, 814),
                  ("CNB", T(12, 20), None, 1, 1007)],
        "coaches": [("S1", "SL"), ("S2", "SL"), ("B1", "3A")],
    },
    {
        "number": "12081", "name": "Malwa Plateau Express", "type": "SUPERFAST", "days": "1111111",
        "description": "Morning superfast to central India.",
        "stops": [("NDLS", None, T(6, 10), 0, 0), ("AGC", T(8, 20), T(8, 25), 0, 195),
                  ("GWL", T(9, 50), T(9, 55), 0, 313), ("BPL", T(14, 30), None, 0, 701)],
        "coaches": [("C1", "CC"), ("S1", "SL"), ("B1", "3A")],
    },
]

# username, first, last, gender, role-specific extras
DEMO_ADMIN = ("admin", "Aditi", "Raman", "admin@sitesmart.demo")
DEMO_TTS = [
    # username, first, last, email, employee id, designation, division, trains
    ("tt_demo", "Vikram", "Rathore", "vikram.tt@sitesmart.demo", "TTE-1001", "SR_TTE", "Lucknow (demo)",
     ["24051", "22907", "19621", "12081"]),
    ("tt_east", "Neha", "Kulkarni", "neha.tt@sitesmart.demo", "TTE-1002", "TTE", "Howrah (demo)",
     ["13511", "15019", "12733"]),
]
DEMO_PASSENGERS = [
    # username, first, last, email, gender, preferred berth
    ("passenger", "Ananya", "Iyer", "ananya@sitesmart.demo", "F", "LB"),
    ("passenger2", "Rohan", "Gupta", "rohan@sitesmart.demo", "M", "UB"),
    ("passenger3", "Meera", "Nair", "meera@sitesmart.demo", "F", ""),
]
# The passenger whose no-show drives the demonstration.
NO_SHOW_PASSENGER = ("rahul.v", "Rahul", "Verma", "rahul@sitesmart.demo", "M")

FIRST_NAMES = ["Aarav", "Ishaan", "Kabir", "Vihaan", "Arjun", "Reyansh", "Aditya", "Krishna", "Sai", "Dhruv",
               "Ayaan", "Advik", "Saanvi", "Aadhya", "Diya", "Kiara", "Myra", "Anika", "Pari", "Navya",
               "Ira", "Tara", "Riya", "Kavya", "Nikhil", "Pooja", "Siddharth", "Lakshmi", "Farhan", "Gurpreet",
               "Joseph", "Fatima", "Harsh", "Snehal", "Tanvi", "Manish", "Deepa", "Imran", "Zoya", "Varun"]
LAST_NAMES = ["Sharma", "Verma", "Patel", "Reddy", "Iyer", "Nair", "Singh", "Gupta", "Das", "Bose", "Menon",
              "Khan", "Joshi", "Kulkarni", "Chatterjee", "Pillai", "Mishra", "Yadav", "Shah", "Agarwal", "D'Souza",
              "Rao", "Saxena", "Bhat", "Ghosh"]
FILLER_USERS = [
    ("kabir.s", "Kabir", "Sharma"), ("diya.p", "Diya", "Patel"), ("arjun.r", "Arjun", "Reddy"),
    ("kavya.m", "Kavya", "Menon"), ("farhan.k", "Farhan", "Khan"), ("tanvi.j", "Tanvi", "Joshi"),
    ("siddharth.b", "Siddharth", "Bose"), ("riya.g", "Riya", "Ghosh"), ("varun.y", "Varun", "Yadav"),
    ("zoya.a", "Zoya", "Agarwal"), ("gurpreet.s", "Gurpreet", "Singh"), ("lakshmi.p", "Lakshmi", "Pillai"),
]
