"""
Featured collections and seed content for the marketplace.

Seeds the store with all built-in OMNIX assets plus community-style
items to give the marketplace a lived-in feel from day one.
"""

from __future__ import annotations

import time
import uuid
import random
from typing import Any

from .models import MarketplaceItem, Review, ItemType
from .store import MarketplaceStore


class FeaturedCollections:
    """Curated marketplace collections."""

    COLLECTIONS = [
        {
            "id": "staff-picks",
            "title": "Staff Picks",
            "icon": "⭐",
            "description": "Hand-picked by the OMNIX team",
            "filter_tags": ["staff-pick"],
        },
        {
            "id": "popular-week",
            "title": "Most Popular This Week",
            "icon": "🔥",
            "description": "Top downloads in the last 7 days",
            "sort": "downloads",
            "limit": 8,
        },
        {
            "id": "beginner",
            "title": "Best for Beginners",
            "icon": "🌱",
            "description": "Start here if you're new to robotics",
            "filter_tags": ["beginner"],
        },
        {
            "id": "industrial",
            "title": "Industrial & Warehouse",
            "icon": "🏭",
            "description": "Robots for manufacturing and logistics",
            "filter_tags": ["industrial"],
        },
        {
            "id": "hobby-drones",
            "title": "Hobby Drones",
            "icon": "🚁",
            "description": "FPV racing, aerial photography, survey drones",
            "filter_tags": ["drone", "hobby"],
        },
        {
            "id": "educational",
            "title": "Educational",
            "icon": "📚",
            "description": "Teaching robotics? Start with these",
            "filter_tags": ["educational"],
        },
    ]

    @staticmethod
    def get_collections(store: MarketplaceStore) -> list[dict]:
        """Return featured collections with their items populated."""
        result = []
        for col in FeaturedCollections.COLLECTIONS:
            items = []
            if "filter_tags" in col:
                browse = store.browse(
                    tags=col["filter_tags"],
                    sort=col.get("sort", "popular"),
                    per_page=col.get("limit", 10),
                )
                items = browse["items"]
            elif col.get("sort"):
                browse = store.browse(
                    sort=col["sort"],
                    per_page=col.get("limit", 10),
                )
                items = browse["items"]

            result.append({
                "id": col["id"],
                "title": col["title"],
                "icon": col["icon"],
                "description": col["description"],
                "items": items,
                "count": len(items),
            })
        return result


# ═══════════════════════════════════════════════════════════
# SEED DATA — populate marketplace with built-in assets
# ═══════════════════════════════════════════════════════════

def _review(item_id, author, rating, comment, days_ago=0):
    return Review(
        review_id=f"rev-{uuid.uuid4().hex[:8]}",
        item_id=item_id,
        author=author,
        rating=rating,
        comment=comment,
        created_at=time.time() - days_ago * 86400,
    )


def seed_marketplace(store: MarketplaceStore) -> int:
    """Populate the marketplace with all built-in OMNIX assets + community items.
    Returns the number of items seeded.
    """
    if store.count() > 0:
        return 0  # Already seeded

    items = []

    # ── 1. Robot Build Templates (10) ────────────────────
    robot_templates = [
        {
            "id": "mkt-quadcopter", "title": "Quadcopter Drone",
            "desc": "Classic X-frame quadrotor UAV with gimbal camera. Perfect for aerial photography, surveying, and learning drone fundamentals. 4 rotors provide stable hover and agile flight characteristics.",
            "tags": ["drone", "quadcopter", "beginner", "aerial", "staff-pick", "hobby"],
            "compat": ["drone"], "icon": "🚁", "downloads": 1847, "rating": 4.7,
            "device_type": "drone", "parts": 6,
        },
        {
            "id": "mkt-6dof-arm", "title": "6-DOF Robotic Arm",
            "desc": "UR5-style industrial arm with 6 revolute joints. Suitable for pick-and-place, assembly, welding, and painting tasks. Includes wrist camera for visual servoing.",
            "tags": ["robot_arm", "industrial", "6dof", "staff-pick"],
            "compat": ["robot_arm"], "icon": "🦾", "downloads": 1356, "rating": 4.8,
            "device_type": "robot_arm", "parts": 8,
        },
        {
            "id": "mkt-rover", "title": "Differential-drive Rover",
            "desc": "TurtleBot-class ground robot with IMU, camera, and ultrasonic sensors. Great for SLAM, navigation research, and classroom demos.",
            "tags": ["ground_robot", "rover", "beginner", "educational", "staff-pick"],
            "compat": ["ground_robot"], "icon": "🤖", "downloads": 2103, "rating": 4.6,
            "device_type": "ground_robot", "parts": 5,
        },
        {
            "id": "mkt-humanoid", "title": "Humanoid (Bipedal)",
            "desc": "Symmetric bipedal robot with twin-camera stereo vision, 2 articulated arms and 2 legs. For balance research, human-robot interaction, and locomotion studies.",
            "tags": ["humanoid", "bipedal", "research"],
            "compat": ["humanoid"], "icon": "🧑‍🤖", "downloads": 892, "rating": 4.5,
            "device_type": "humanoid", "parts": 12,
        },
        {
            "id": "mkt-hexapod", "title": "Hexapod Robot",
            "desc": "6-legged crawler with 3-DOF articulated limbs. Handles rough terrain and inclines. Bio-inspired tripod gait for stable locomotion.",
            "tags": ["legged", "hexapod", "research", "outdoor"],
            "compat": ["legged"], "icon": "🕷️", "downloads": 673, "rating": 4.4,
            "device_type": "legged", "parts": 19,
        },
        {
            "id": "mkt-agv", "title": "Warehouse AGV",
            "desc": "Flat-platform 4-wheel AGV with lidar and safety laser scanners. Designed for autonomous warehouse navigation, shelf transport, and goods-to-person fulfillment.",
            "tags": ["ground_robot", "agv", "industrial", "warehouse", "staff-pick"],
            "compat": ["ground_robot"], "icon": "📦", "downloads": 1589, "rating": 4.7,
            "device_type": "ground_robot", "parts": 7,
        },
        {
            "id": "mkt-fixed-wing", "title": "Fixed-wing UAV",
            "desc": "Main wing with stabilizers and pusher prop. Long endurance for mapping, agriculture, and surveillance. Efficient cruise flight with VTOL transition support.",
            "tags": ["drone", "fixed-wing", "survey", "agriculture"],
            "compat": ["drone"], "icon": "✈️", "downloads": 956, "rating": 4.3,
            "device_type": "drone", "parts": 5,
        },
        {
            "id": "mkt-gripper", "title": "End-effector Gripper",
            "desc": "2-finger parallel gripper with wrist rotation and force sensor. Precision grasping for assembly lines and bin-picking. Mounts on any compatible arm.",
            "tags": ["robot_arm", "gripper", "industrial", "end-effector"],
            "compat": ["robot_arm"], "icon": "🤏", "downloads": 743, "rating": 4.5,
            "device_type": "robot_arm", "parts": 4,
        },
        {
            "id": "mkt-quadruped", "title": "Quadruped (Spot-style)",
            "desc": "4-legged dog-class robot with head camera, IMU, and 12-DOF legs. Dynamic gaits: walk, trot, bound. Navigates stairs, rubble, and outdoor terrain.",
            "tags": ["legged", "quadruped", "outdoor", "inspection", "staff-pick"],
            "compat": ["legged"], "icon": "🐕", "downloads": 1234, "rating": 4.8,
            "device_type": "legged", "parts": 14,
        },
        {
            "id": "mkt-rov", "title": "Underwater ROV",
            "desc": "Cylindrical pressure hull with 6 thrusters, HD dome camera, and sonar. For underwater inspection, marine research, and subsea maintenance operations.",
            "tags": ["marine", "rov", "underwater", "research"],
            "compat": ["marine"], "icon": "🐟", "downloads": 421, "rating": 4.2,
            "device_type": "marine", "parts": 9,
        },
    ]

    for rt in robot_templates:
        item = MarketplaceItem(
            item_id=rt["id"],
            item_type=ItemType.ROBOT_BUILD,
            title=rt["title"],
            description=rt["desc"],
            author="OMNIX Team",
            version="1.0.0",
            tags=rt["tags"],
            downloads=rt["downloads"],
            rating=rt["rating"],
            rating_count=random.randint(8, 45),
            compatibility=rt["compat"],
            icon=rt["icon"],
            featured="staff-pick" in rt["tags"],
            payload={
                "device_type": rt["device_type"],
                "part_count": rt["parts"],
                "template_id": rt["id"].replace("mkt-", ""),
            },
        )
        items.append(item)

    # ── 2. Mission Templates (6) ─────────────────────────
    mission_templates = [
        {
            "id": "mkt-mission-patrol", "title": "Patrol & Return",
            "desc": "Fly a patrol loop through configurable waypoints, then return to home position. Battery pre-check ensures safe operation. 3 laps by default.",
            "tags": ["mission", "patrol", "drone", "beginner", "staff-pick"],
            "compat": ["drone", "ground_robot"], "icon": "🔄",
            "downloads": 1245, "rating": 4.6,
        },
        {
            "id": "mkt-mission-search", "title": "Search & Report",
            "desc": "Systematic grid scan over a defined area. Pauses at each scan point for observation and logging. Great for area surveys and search operations.",
            "tags": ["mission", "search", "survey", "drone"],
            "compat": ["drone", "ground_robot"], "icon": "🔍",
            "downloads": 987, "rating": 4.5,
        },
        {
            "id": "mkt-mission-sentry", "title": "Sentry Mode",
            "desc": "Hover at a designated watch post and continuously monitor telemetry. Emits alerts when battery drops or anomalies are detected. Autonomous watchdog.",
            "tags": ["mission", "sentry", "security", "drone", "staff-pick"],
            "compat": ["drone"], "icon": "👁️",
            "downloads": 1102, "rating": 4.7,
        },
        {
            "id": "mkt-mission-pickplace", "title": "Pick & Place Cycle",
            "desc": "Robot arm picks objects from position A and places at position B in a repeating cycle. Configurable repetitions and gripper timing.",
            "tags": ["mission", "pick-place", "robot_arm", "industrial"],
            "compat": ["robot_arm"], "icon": "🦾",
            "downloads": 876, "rating": 4.4,
        },
        {
            "id": "mkt-mission-path", "title": "Follow Path",
            "desc": "Navigate through a predefined sequence of coordinate waypoints. Useful for repeatable routes, delivery paths, and survey transects.",
            "tags": ["mission", "path", "navigation", "beginner"],
            "compat": ["drone", "ground_robot"], "icon": "📍",
            "downloads": 1034, "rating": 4.3,
        },
        {
            "id": "mkt-mission-emergency", "title": "Emergency Response",
            "desc": "Intelligent emergency handler with fallback logic. Assesses battery and system health, attempts controlled return-to-home, or executes emergency landing if critical.",
            "tags": ["mission", "emergency", "safety", "staff-pick"],
            "compat": ["drone", "ground_robot", "robot_arm"], "icon": "🚨",
            "downloads": 1567, "rating": 4.9,
        },
    ]

    for mt in mission_templates:
        item = MarketplaceItem(
            item_id=mt["id"],
            item_type=ItemType.MISSION_TEMPLATE,
            title=mt["title"],
            description=mt["desc"],
            author="OMNIX Team",
            version="1.0.0",
            tags=mt["tags"],
            downloads=mt["downloads"],
            rating=mt["rating"],
            rating_count=random.randint(5, 30),
            compatibility=mt["compat"],
            icon=mt["icon"],
            featured="staff-pick" in mt["tags"],
            payload={"template_name": mt["title"]},
        )
        items.append(item)

    # ── 3. Connectors (6) ────────────────────────────────
    connectors = [
        {
            "id": "mkt-conn-pi", "title": "Raspberry Pi Agent",
            "desc": "DIY Pi-based robots. Run the OMNIX agent on your Pi — it auto-registers over HTTP. Supports camera, GPIO, I2C, and SPI peripherals.",
            "tags": ["connector", "raspberry-pi", "diy", "beginner", "educational"],
            "icon": "🍓", "downloads": 2341, "rating": 4.6,
            "connector_id": "pi_agent",
        },
        {
            "id": "mkt-conn-arduino", "title": "Arduino (USB Serial)",
            "desc": "Arduino, Teensy, and RP2040 over USB serial. Flash the OMNIX firmware sketch, plug in, pick the port. Supports rover, arm, and sensor boards.",
            "tags": ["connector", "arduino", "serial", "beginner", "educational"],
            "icon": "🔵", "downloads": 1876, "rating": 4.5,
            "connector_id": "arduino_serial",
        },
        {
            "id": "mkt-conn-esp32", "title": "ESP32 (Wi-Fi Agent)",
            "desc": "ESP32/ESP8266/ESP32-S3 over Wi-Fi. Wireless connectivity for IoT robots, smart home devices, and sensor nodes.",
            "tags": ["connector", "esp32", "wifi", "iot"],
            "icon": "📶", "downloads": 1543, "rating": 4.4,
            "connector_id": "esp32_wifi",
        },
        {
            "id": "mkt-conn-tello", "title": "DJI Tello",
            "desc": "Direct integration with DJI Tello and Tello EDU drones. Takeoff, land, flip, stream video — all through OMNIX.",
            "tags": ["connector", "tello", "dji", "drone", "educational", "hobby", "staff-pick"],
            "icon": "🎮", "downloads": 2567, "rating": 4.8,
            "connector_id": "tello",
        },
        {
            "id": "mkt-conn-mavlink", "title": "MAVLink (PX4 / ArduPilot)",
            "desc": "Any MAVLink-speaking vehicle: PX4, ArduPilot Copter/Plane/Rover/Sub. Serial, UDP, or TCP connection. Professional-grade flight control.",
            "tags": ["connector", "mavlink", "px4", "ardupilot", "professional"],
            "icon": "🛩️", "downloads": 1234, "rating": 4.7,
            "connector_id": "mavlink",
        },
        {
            "id": "mkt-conn-ros2", "title": "ROS2 Bridge",
            "desc": "Bridge OMNIX to any ROS2 ecosystem. Publish/subscribe to topics, call services, send actions. Full Humble/Iron/Jazzy compatibility.",
            "tags": ["connector", "ros2", "ros", "research", "professional"],
            "icon": "🌐", "downloads": 1089, "rating": 4.6,
            "connector_id": "ros2_bridge",
        },
    ]

    for c in connectors:
        item = MarketplaceItem(
            item_id=c["id"],
            item_type=ItemType.CONNECTOR,
            title=c["title"],
            description=c["desc"],
            author="OMNIX Team",
            version="1.0.0",
            tags=c["tags"],
            downloads=c["downloads"],
            rating=c["rating"],
            rating_count=random.randint(10, 50),
            compatibility=[],
            icon=c["icon"],
            featured="staff-pick" in c["tags"],
            payload={"connector_id": c["connector_id"]},
        )
        items.append(item)

    # ── 4. Community-style items (10 extra) ──────────────
    community = [
        {
            "id": "mkt-racing-drone", "title": "Racing Drone (Optimized)",
            "type": ItemType.ROBOT_BUILD,
            "desc": "Competition-ready FPV racing drone with optimized thrust-to-weight ratio. Aggressive PID tuning, lightweight carbon frame, and 5-inch props. Sub-200g AUW for freestyle.",
            "author": "DroneRacer42",
            "tags": ["drone", "racing", "fpv", "hobby", "competition"],
            "compat": ["drone"], "icon": "🏎️", "downloads": 3421, "rating": 4.9,
        },
        {
            "id": "mkt-warehouse-patrol", "title": "Warehouse Patrol Bot",
            "type": ItemType.ROBOT_BUILD,
            "desc": "Autonomous warehouse patrol robot with lidar mapping, zone-based scheduling, and anomaly detection. Reports inventory gaps and safety hazards on each patrol cycle.",
            "author": "LogisticsLab",
            "tags": ["ground_robot", "warehouse", "industrial", "patrol", "staff-pick"],
            "compat": ["ground_robot"], "icon": "🏭", "downloads": 1876, "rating": 4.7,
        },
        {
            "id": "mkt-agri-surveyor", "title": "Agricultural Surveyor Drone",
            "type": ItemType.ROBOT_BUILD,
            "desc": "Fixed-wing drone configured for agricultural surveys. NDVI-compatible camera payload, long endurance (45+ min), automated flight planning over field boundaries.",
            "author": "AgTech_Pioneer",
            "tags": ["drone", "agriculture", "survey", "fixed-wing", "outdoor"],
            "compat": ["drone"], "icon": "🌾", "downloads": 1543, "rating": 4.6,
        },
        {
            "id": "mkt-classroom-kit", "title": "Classroom Robot Kit",
            "type": ItemType.ROBOT_BUILD,
            "desc": "Educational robot designed for K-12 and university courses. Simple differential drive with bump sensors, line followers, and LED feedback. Includes lesson plan missions.",
            "author": "EduBots",
            "tags": ["ground_robot", "educational", "beginner", "classroom", "staff-pick"],
            "compat": ["ground_robot"], "icon": "📚", "downloads": 4231, "rating": 4.8,
        },
        {
            "id": "mkt-security-sentry", "title": "Home Security Sentry",
            "type": ItemType.ROBOT_BUILD,
            "desc": "Indoor patrol robot with 360-degree camera, motion detection, and automated alert system. Navigates between rooms on a schedule and reports anomalies to your phone.",
            "author": "SmartHomeHQ",
            "tags": ["ground_robot", "security", "home", "indoor", "hobby"],
            "compat": ["ground_robot"], "icon": "🛡️", "downloads": 2156, "rating": 4.5,
        },
        {
            "id": "mkt-delivery-bot", "title": "Last-Mile Delivery Bot",
            "type": ItemType.ROBOT_BUILD,
            "desc": "Sidewalk delivery robot with compartment lock, GPS waypoint navigation, obstacle avoidance, and customer notification system. Weatherproof design.",
            "author": "UrbanRobotics",
            "tags": ["ground_robot", "delivery", "outdoor", "industrial"],
            "compat": ["ground_robot"], "icon": "📬", "downloads": 987, "rating": 4.3,
        },
        {
            "id": "mkt-inspection-quad", "title": "Infrastructure Inspector",
            "type": ItemType.ROBOT_BUILD,
            "desc": "Heavy-lift inspection drone with thermal + RGB dual camera, RTK GPS, and automated bridge/tower scanning patterns. Export reports with defect annotations.",
            "author": "InfraSpec",
            "tags": ["drone", "inspection", "industrial", "professional"],
            "compat": ["drone"], "icon": "🔍", "downloads": 876, "rating": 4.6,
        },
        {
            "id": "mkt-mission-mapping", "title": "Automated Area Mapping",
            "type": ItemType.MISSION_TEMPLATE,
            "desc": "Fly a systematic lawnmower pattern to map a rectangular area. Configurable altitude, overlap percentage, and camera trigger interval. Outputs GeoTIFF-ready waypoints.",
            "author": "MapperPro",
            "tags": ["mission", "mapping", "survey", "drone", "professional"],
            "compat": ["drone"], "icon": "🗺️", "downloads": 2134, "rating": 4.7,
        },
        {
            "id": "mkt-mission-inventory", "title": "Warehouse Inventory Scan",
            "type": ItemType.MISSION_TEMPLATE,
            "desc": "Autonomous aisle-by-aisle inventory scanning mission. Navigates warehouse aisles, reads barcodes at each shelf level, and logs discrepancies. Works with ground robots and drones.",
            "author": "LogisticsLab",
            "tags": ["mission", "inventory", "warehouse", "industrial"],
            "compat": ["ground_robot", "drone"], "icon": "📋", "downloads": 1456, "rating": 4.5,
        },
        {
            "id": "mkt-physics-tello", "title": "Tello Flight Model (Tuned)",
            "type": ItemType.PHYSICS_PROFILE,
            "desc": "Pre-tuned physics profile for DJI Tello drones based on 500+ real-world flight recordings. Accurate hover, wind response, and battery curves. Plug-and-play for Tello Digital Twin.",
            "author": "DronePhysics",
            "tags": ["physics", "tello", "drone", "calibrated"],
            "compat": ["drone"], "icon": "⚙️", "downloads": 1678, "rating": 4.8,
        },
    ]

    for c in community:
        item = MarketplaceItem(
            item_id=c["id"],
            item_type=c.get("type", ItemType.ROBOT_BUILD),
            title=c["title"],
            description=c["desc"],
            author=c.get("author", "Community"),
            version="1.0.0",
            tags=c["tags"],
            downloads=c["downloads"],
            rating=c["rating"],
            rating_count=random.randint(5, 60),
            compatibility=c.get("compat", []),
            icon=c["icon"],
            featured="staff-pick" in c["tags"],
            payload=c.get("payload", {}),
        )
        items.append(item)

    # ── Add sample reviews to popular items ──────────────
    review_pool = [
        ("RoboHacker", 5, "Perfect for getting started! Configured in minutes."),
        ("DroneEnthusiast", 4, "Solid design. Would love more sensor options."),
        ("LabTech99", 5, "Used this in our university course. Students loved it."),
        ("MechBuilder", 4, "Great base to customize from. Clean part layout."),
        ("FPV_Mike", 5, "Best racing frame I've found. Incredibly responsive."),
        ("WarehouseOps", 5, "Transformed our inventory process. Highly recommend."),
        ("HobbyPilot", 4, "Fun to fly. Simulator accuracy is impressive."),
        ("IndustrialDev", 5, "Professional quality. Using this in production."),
        ("TeachBot", 5, "My students understand robotics so much better now."),
        ("AutomationPro", 4, "Good documentation. Easy to adapt to our needs."),
        ("AerialMapper", 5, "Saved us hours of manual surveying work."),
        ("TechLead_Sarah", 4, "Clean integration with our existing ROS2 setup."),
    ]

    for item in items:
        # Add 2-4 reviews to each item
        n_reviews = random.randint(2, 4)
        sample = random.sample(review_pool, min(n_reviews, len(review_pool)))
        for author, rating, comment in sample:
            item.add_review(_review(
                item.item_id, author, rating, comment,
                days_ago=random.randint(1, 90),
            ))

    # ── Insert all items ─────────────────────────────────
    for item in items:
        store.add(item)

    return len(items)
