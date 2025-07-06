import json
import requests
from datetime import datetime, timedelta
import pytz
import functions_framework
import os
import logging

# Set up logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Try to load dotenv, but don't fail if it's not available
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    logger.warning("python-dotenv not available, using environment variables directly")

# Cal.com API configuration
CAL_API_KEY = os.getenv("CAL_API_KEY")
CAL_BASE_URL = "https://api.cal.com/v1"
EVENT_TYPE_ID = 2733973  

# Validate required environment variables
if not CAL_API_KEY:
    logger.error("CAL_API_KEY environment variable is not set")

@functions_framework.http
def cal_api(request):
    """Main function that handles all routes"""
    
    logger.info(f"Received request: {request.method} {request.path}")
    
    # Enable CORS for all requests
    if request.method == 'OPTIONS':
        headers = {
            'Access-Control-Allow-Origin': '*',
            'Access-Control-Allow-Methods': 'GET, POST, DELETE, OPTIONS',
            'Access-Control-Allow-Headers': 'Content-Type',
            'Access-Control-Max-Age': '3600'
        }
        return ('', 204, headers)
    
    # Set CORS headers for actual requests
    headers = {
        'Access-Control-Allow-Origin': '*',
        'Content-Type': 'application/json'
    }
    
    # Check if API key is available
    if not CAL_API_KEY:
        error_response = json.dumps({"error": "API key not configured"})
        return (error_response, 500, headers)
    
    # Get the path from the request
    path = request.path.rstrip('/')  # Remove trailing slash
    method = request.method
    
    logger.info(f"Processing path: '{path}' with method: {method}")
    
    try:
        # Route to appropriate handler
        if path == '' or path == '/':
            response_data, status_code = home_handler(request)
        elif path == '/book':
            response_data, status_code = create_booking_handler(request)
        elif path == '/cancel':
            response_data, status_code = cancel_booking_handler(request)
        elif path == '/availability':
            response_data, status_code = get_availability_handler(request)
        elif path == '/allbookings':
            response_data, status_code = get_bookings_handler(request)
        else:
            logger.warning(f"Unknown endpoint: {path}")
            response_data = json.dumps({"error": f"Endpoint not found: {path}"})
            status_code = 404
            
        logger.info(f"Response status: {status_code}")
        return (response_data, status_code, headers)
        
    except Exception as e:
        logger.error(f"Unexpected error in main handler: {str(e)}", exc_info=True)
        error_response = json.dumps({"error": "Internal server error", "details": str(e)})
        return (error_response, 500, headers)

def home_handler(request):
    """Home endpoint"""
    return json.dumps({
        "message": "Cal.com Cloud Function API", 
        "endpoints": [
            "POST /book - Create a booking",
            "DELETE /cancel - Cancel a booking", 
            "GET /availability - Get availability",
            "GET /allbookings - Get all bookings"
        ],
        "status": "healthy"
    }), 200

def create_booking_handler(request):
    """Create a booking"""
    try:
        if request.method != 'POST':
            return json.dumps({"error": "Method not allowed"}), 405
        
        # Get JSON data with error handling
        try:
            data = request.get_json()
        except Exception as e:
            logger.error(f"Error parsing JSON: {e}")
            return json.dumps({"error": "Invalid JSON format"}), 400
            
        if not data:
            return json.dumps({"error": "No JSON data provided"}), 400
        
        logger.info(f"Received booking data: {json.dumps(data, indent=2)}")
        
        # Required fields validation
        required_fields = ['start', 'name', 'email']
        for field in required_fields:
            if field not in data:
                return json.dumps({"error": f"Missing required field: {field}"}), 400
        
        url = f"{CAL_BASE_URL}/bookings"
        querystring = {"apiKey": CAL_API_KEY}

        # Parse and adjust time with better error handling
        try:
            # Handle different datetime formats
            start_time_str = data['start']
            if 'T' in start_time_str:
                original_time = datetime.fromisoformat(start_time_str.replace('Z', '+00:00'))
            else:
                original_time = datetime.strptime(start_time_str, '%Y-%m-%d %H:%M:%S')
            
            # Adjust time (subtract 5:30 for IST to UTC conversion)
            adjusted_time = original_time - timedelta(hours=5, minutes=30)
            logger.info(f"Original time: {original_time}, Adjusted time: {adjusted_time}")
            
        except ValueError as e:
            logger.error(f"Date parsing error: {e}")
            return json.dumps({"error": f"Invalid date format: {str(e)}. Expected ISO format or YYYY-MM-DD HH:MM:SS"}), 400
            
        payload = {
            "eventTypeId": EVENT_TYPE_ID,
            "start": adjusted_time.isoformat(),
            "responses": {
                "name": data['name'],
                "email": data['email'],
                "location": data.get('location', {
                    "value": "https://zoom.us/my/doctor", 
                    "optionValue": "video"
                }),
            },
            "description": data['description'] if 'description' in data else None,
            "metadata": data.get('metadata', {
                "source": "AI Assistant",
                "bookingType": "Consultation"
            }),
            "timeZone": data.get('timeZone', "Asia/Kolkata"),
            "language": data.get('language', "en"),
        }
        
        # Add optional fields only if they exist
        if 'description' in data and data['description']:
            payload["description"] = data['description']
            
        if 'metadata' in data:
            payload["metadata"] = data['metadata']
        else:
            payload["metadata"] = {
                "source": "AI Assistant",
                "bookingType": "Consultation"
            }
        
        headers = {"Content-Type": "application/json"}
        
        logger.info(f"Sending booking request to: {url}")
        logger.info(f"Payload: {json.dumps(payload, indent=2)}")
        
        response = requests.post(url, json=payload, headers=headers, params=querystring, timeout=30)
        
        logger.info(f"Cal.com API response status: {response.status_code}")
        logger.info(f"Cal.com API response: {response.text}")
        
        if response.status_code >= 400:
            return json.dumps({
                "error": "Booking failed",
                "status_code": response.status_code,
                "details": response.json() if response.content else "No response content"
            }), response.status_code
        
        appointment = response.json()
        start_time = appointment.get("startTime", "")
        end_time = appointment.get("endTime", "")

        return json.dumps({
            "success": True,
            "appointment": {
                "booking_id": appointment.get("id"),
                "date": start_time.split("T")[0] if start_time else "",
                "start_time": start_time.split("T")[1][:5] if start_time else "",
                "end_time": end_time.split("T")[1][:5] if end_time else "",
            }
        }), response.status_code
        
    except requests.exceptions.RequestException as e:
        logger.error(f"Request error creating booking: {e}")
        return json.dumps({"error": "External API request failed", "details": str(e)}), 503
    except Exception as e:
        logger.error(f"Error creating booking: {e}", exc_info=True)
        return json.dumps({"error": "Internal server error", "details": str(e)}), 500

def cancel_booking_handler(request):
    """Cancel a booking"""
    try:
        if request.method != 'DELETE':
            return json.dumps({"error": "Method not allowed"}), 405
            
        booking_id = request.args.get('booking_id')
        if not booking_id:
            return json.dumps({"error": "Missing required parameter: booking_id"}), 400

        cancellation_reason = request.args.get('cancellationReason', 'Cancelled via API')
        
        url = f"{CAL_BASE_URL}/bookings/{booking_id}/cancel"
        querystring = {
            "apiKey": CAL_API_KEY,
            "cancellationReason": cancellation_reason
        }
        
        logger.info(f"Cancelling booking {booking_id}")
        response = requests.delete(url, params=querystring, timeout=30)
        
        logger.info(f"Cancellation response status: {response.status_code}")
        
        return json.dumps({
            "success": response.status_code < 400,
            "status_code": response.status_code,
            "response": response.json() if response.content else {"message": "Booking cancelled successfully"}
        }), response.status_code
        
    except requests.exceptions.RequestException as e:
        logger.error(f"Request error cancelling booking {booking_id}: {e}")
        return json.dumps({"error": "External API request failed", "details": str(e)}), 503
    except Exception as e:
        logger.error(f"Error cancelling booking {booking_id}: {e}", exc_info=True)
        return json.dumps({"error": "Internal server error", "details": str(e)}), 500

def get_availability_handler(request):
    """Get availability - check specific slot or return all available slots"""
    try:
        if request.method != 'GET':
            return json.dumps({"error": "Method not allowed"}), 405
            
        # Get query parameters
        date_from = request.args.get('dateFrom')
        time = request.args.get('time')  # Expected format: HH:MM (e.g., "14:30")
        date_to = request.args.get('dateTo') 

        # Default dates if not provided
        if not date_from:
            date_from = datetime.now().strftime('%Y-%m-%d')
        if not date_to:
            date_to = date_from
        
        logger.info(f"Checking availability from {date_from} to {date_to}")
        if time:
            logger.info(f"Specific time requested: {time}")
        
        # Validate date format
        try:
            date_obj = datetime.strptime(date_from, '%Y-%m-%d')
        except ValueError:
            return json.dumps({"error": "Invalid date format. Use YYYY-MM-DD"}), 400
        
        # Validate time format if provided
        requested_datetime = None
        if time:
            try:
                time_obj = datetime.strptime(time, '%H:%M').time()
                requested_datetime = datetime.combine(date_obj.date(), time_obj)
                # Convert to IST timezone for comparison
                ist = pytz.timezone("Asia/Kolkata")
                requested_datetime = ist.localize(requested_datetime)
            except ValueError:
                return json.dumps({"error": "Invalid time format. Use HH:MM (e.g., 14:30)"}), 400
            
        start_time = date_obj.replace(hour=9, minute=0, second=0).strftime('%Y-%m-%dT%H:%M:%S+05:30')
        end_time = date_obj.replace(hour=17, minute=0, second=0).strftime('%Y-%m-%dT%H:%M:%S+05:30')
        
        url = f"{CAL_BASE_URL}/slots"
        querystring = {
            "apiKey": CAL_API_KEY,
            "eventTypeId": EVENT_TYPE_ID,
            "startTime": start_time,
            "endTime": end_time
        }
    
        logger.info(f"Fetching slots from: {url}")
        response = requests.get(url, params=querystring, timeout=30)
        
        logger.info(f"Slots API response status: {response.status_code}")
        
        if response.status_code == 200:
            data = response.json()
            slots = data.get("slots", {})
            ist = pytz.timezone("Asia/Kolkata")
            available_slots = []
            slot_found = False
            
            # Process slots and convert to IST
            for date, slot_list in slots.items():
                for slot in slot_list:
                    try:
                        utc_time = datetime.strptime(slot["time"], "%Y-%m-%dT%H:%M:%S.000Z")
                        utc_time = utc_time.replace(tzinfo=pytz.utc)
                        ist_time = utc_time.astimezone(ist)
                        
                        # Add to available slots list
                        available_slots.append({
                            "datetime": ist_time.strftime("%Y-%m-%d %H:%M:%S IST"),
                            "date": ist_time.strftime("%Y-%m-%d"),
                            "time": ist_time.strftime("%H:%M")
                        })
                        
                        # Check if this matches the requested time
                        if requested_datetime:
                            # Compare date and time (ignoring seconds)
                            if (ist_time.date() == requested_datetime.date() and 
                                ist_time.hour == requested_datetime.hour and 
                                ist_time.minute == requested_datetime.minute):
                                slot_found = True
                                
                    except (ValueError, KeyError) as e:
                        logger.error(f"Error parsing slot time: {e}")
                        continue
            
            # Sort available slots by datetime
            available_slots.sort(key=lambda x: x["datetime"])
            
            # If specific time was requested, check if it's available
            if time and requested_datetime:
                if slot_found:
                    return json.dumps({
                        "success": True,
                        "slot_available": True,
                        "requested_slot": {
                            "date": date_from,
                            "time": time,
                            "datetime": requested_datetime.strftime("%Y-%m-%d %H:%M:%S IST")
                        },
                        "message": f"Slot is available on {date_from} at {time}"
                    }), 200
                else:
                    return json.dumps({
                        "success": True,
                        "slot_available": False,
                        "requested_slot": {
                            "date": date_from,
                            "time": time,
                            "datetime": requested_datetime.strftime("%Y-%m-%d %H:%M:%S IST")
                        },
                        "message": f"Slot is not available on {date_from} at {time}",
                        "available_slots": available_slots,
                        "total_available_slots": len(available_slots)
                    }), 200
            else:
                # Return all available slots if no specific time requested
                return json.dumps({
                    "success": True,
                    "available_slots": available_slots,
                    "total_slots": len(available_slots),
                    "date_range": f"{date_from} to {date_to}"
                }), 200
        else:
            return json.dumps({
                "success": False,
                "status_code": response.status_code,
                "error": "Failed to fetch slots",
                "response": response.json() if response.content else None
            }), response.status_code
        
    except requests.exceptions.RequestException as e:
        logger.error(f"Request error fetching availability: {e}")
        return json.dumps({"error": "External API request failed", "details": str(e)}), 503
    except Exception as e:
        logger.error(f"Error fetching availability: {e}", exc_info=True)
        return json.dumps({"error": "Internal server error", "details": str(e)}), 500

def get_bookings_handler(request):
    """Get all bookings"""
    try:
        if request.method != 'GET':
            return json.dumps({"error": "Method not allowed"}), 405
            
        url = f"{CAL_BASE_URL}/attendees"
        querystring = {"apiKey": CAL_API_KEY}
        
        logger.info(f"Fetching all bookings from: {url}")
        response = requests.get(url, params=querystring, timeout=30)
        
        logger.info(f"Bookings API response status: {response.status_code}")
        
        return json.dumps({
            "success": response.status_code < 400,
            "status_code": response.status_code,
            "response": response.json() if response.content else None
        }), response.status_code
        
    except requests.exceptions.RequestException as e:
        logger.error(f"Request error fetching bookings: {e}")
        return json.dumps({"error": "External API request failed", "details": str(e)}), 503
    except Exception as e:
        logger.error(f"Error fetching bookings: {e}", exc_info=True)
        return json.dumps({"error": "Internal server error", "details": str(e)}), 500