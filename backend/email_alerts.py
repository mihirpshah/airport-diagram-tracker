"""
email_alerts.py - Send email alerts when airport diagram changes are detected

Uses Gmail SMTP with an App Password for authentication.
To set up:
1. Go to Google Account > Security > 2-Step Verification (enable it)
2. Go to Google Account > Security > App passwords
3. Generate a new app password for "Mail"
4. Use that 16-character password as GMAIL_APP_PASSWORD

Environment variables required:
- GMAIL_ADDRESS: Your Gmail address (e.g., your.email@gmail.com)
- GMAIL_APP_PASSWORD: The 16-character app password from Google
- ALERT_RECIPIENT_EMAIL: Email address to send alerts to (can be same as GMAIL_ADDRESS)
"""

import os
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from datetime import datetime
from typing import List, Dict, Optional


def get_email_config() -> Dict[str, str]:
    """
    Get email configuration from environment variables.
    Returns dict with gmail_address, gmail_password, recipient_email.
    """
    return {
        'gmail_address': os.environ.get('GMAIL_ADDRESS', ''),
        'gmail_password': os.environ.get('GMAIL_APP_PASSWORD', ''),
        'recipient_email': os.environ.get('ALERT_RECIPIENT_EMAIL', '')
    }


def is_email_configured() -> bool:
    """Check if email alerts are properly configured."""
    config = get_email_config()
    return all([
        config['gmail_address'],
        config['gmail_password'],
        config['recipient_email']
    ])


def send_change_alert(
    airport_code: str,
    old_cycle: str,
    new_cycle: str,
    taxiway_changes: List[Dict],
    runway_changes: List[Dict],
    app_url: str = ""
) -> bool:
    """
    Send an email alert about detected airport diagram changes.

    Args:
        airport_code: The airport code (e.g., "JFK")
        old_cycle: Previous AIRAC cycle (e.g., "2601")
        new_cycle: Current AIRAC cycle (e.g., "2602")
        taxiway_changes: List of taxiway change dictionaries
        runway_changes: List of runway change dictionaries
        app_url: URL to the web app for viewing details

    Returns:
        True if email sent successfully, False otherwise
    """
    if not is_email_configured():
        print("Email alerts not configured. Set GMAIL_ADDRESS, GMAIL_APP_PASSWORD, and ALERT_RECIPIENT_EMAIL.")
        return False

    config = get_email_config()

    # Build the email subject
    total_changes = len(taxiway_changes) + len(runway_changes)
    subject = f"🛫 Airport Diagram Alert: {airport_code} has {total_changes} change(s) in cycle {new_cycle}"

    # Build the email body (plain text version)
    body_text = f"""
Airport Diagram Change Alert
=============================

Airport: {airport_code}
Cycle: {old_cycle} → {new_cycle}
Detected: {datetime.now().strftime('%Y-%m-%d %H:%M UTC')}

"""

    if taxiway_changes:
        body_text += f"TAXIWAY CHANGES ({len(taxiway_changes)}):\n"
        body_text += "-" * 40 + "\n"
        for change in taxiway_changes:
            body_text += f"  • {change.get('change_type', 'CHANGE')}: {change.get('description', change.get('designator', 'Unknown'))}\n"
        body_text += "\n"

    if runway_changes:
        body_text += f"RUNWAY CHANGES ({len(runway_changes)}):\n"
        body_text += "-" * 40 + "\n"
        for change in runway_changes:
            body_text += f"  • {change.get('change_type', 'CHANGE')}: {change.get('description', change.get('designator', 'Unknown'))}\n"
        body_text += "\n"

    if app_url:
        body_text += f"\nView details: {app_url}\n"

    body_text += """
---
This alert was sent by Airport Diagram Change Tracker.
Configure alerts at: https://github.com/your-repo/airport-diagram-tracker
"""

    # Build the HTML version (nicer formatting)
    body_html = f"""
<html>
<head>
    <style>
        body {{ font-family: Arial, sans-serif; max-width: 600px; margin: 0 auto; padding: 20px; }}
        .header {{ background: #1e40af; color: white; padding: 20px; border-radius: 8px 8px 0 0; }}
        .content {{ background: #f8fafc; padding: 20px; border: 1px solid #e2e8f0; }}
        .change-section {{ margin: 15px 0; }}
        .change-title {{ font-weight: bold; color: #1e40af; margin-bottom: 10px; }}
        .change-item {{ padding: 8px 12px; margin: 5px 0; border-radius: 4px; }}
        .added {{ background: #dcfce7; border-left: 4px solid #16a34a; }}
        .removed {{ background: #fee2e2; border-left: 4px solid #dc2626; }}
        .renamed {{ background: #fef3c7; border-left: 4px solid #d97706; }}
        .runway {{ background: #ede9fe; border-left: 4px solid #7c3aed; }}
        .footer {{ font-size: 12px; color: #64748b; margin-top: 20px; padding-top: 20px; border-top: 1px solid #e2e8f0; }}
        .btn {{ display: inline-block; background: #1e40af; color: white; padding: 10px 20px; text-decoration: none; border-radius: 4px; margin-top: 15px; }}
    </style>
</head>
<body>
    <div class="header">
        <h1 style="margin: 0;">🛫 Airport Diagram Change Alert</h1>
        <p style="margin: 10px 0 0 0; opacity: 0.9;">{airport_code} • Cycle {old_cycle} → {new_cycle}</p>
    </div>
    <div class="content">
        <p><strong>Detected:</strong> {datetime.now().strftime('%Y-%m-%d %H:%M UTC')}</p>
"""

    if taxiway_changes:
        body_html += f"""
        <div class="change-section">
            <div class="change-title">Taxiway Changes ({len(taxiway_changes)})</div>
"""
        for change in taxiway_changes:
            change_type = change.get('change_type', 'CHANGE').lower()
            css_class = 'added' if 'added' in change_type else ('removed' if 'removed' in change_type else 'renamed')
            body_html += f"""
            <div class="change-item {css_class}">
                <strong>{change.get('change_type', 'CHANGE')}:</strong> {change.get('description', change.get('designator', 'Unknown'))}
            </div>
"""
        body_html += "</div>"

    if runway_changes:
        body_html += f"""
        <div class="change-section">
            <div class="change-title">Runway Changes ({len(runway_changes)})</div>
"""
        for change in runway_changes:
            body_html += f"""
            <div class="change-item runway">
                <strong>{change.get('change_type', 'CHANGE')}:</strong> {change.get('description', change.get('designator', 'Unknown'))}
            </div>
"""
        body_html += "</div>"

    if app_url:
        body_html += f"""
        <a href="{app_url}" class="btn">View Full Details →</a>
"""

    body_html += """
        <div class="footer">
            <p>This alert was sent by Airport Diagram Change Tracker.</p>
            <p>FAA diagrams are updated every 28 days (AIRAC cycle).</p>
        </div>
    </div>
</body>
</html>
"""

    # Create the email message
    msg = MIMEMultipart('alternative')
    msg['Subject'] = subject
    msg['From'] = config['gmail_address']
    msg['To'] = config['recipient_email']

    # Attach both plain text and HTML versions
    msg.attach(MIMEText(body_text, 'plain'))
    msg.attach(MIMEText(body_html, 'html'))

    try:
        # Connect to Gmail SMTP server
        with smtplib.SMTP_SSL('smtp.gmail.com', 465) as server:
            server.login(config['gmail_address'], config['gmail_password'])
            server.send_message(msg)

        print(f"✅ Alert email sent to {config['recipient_email']} for {airport_code}")
        return True

    except smtplib.SMTPAuthenticationError as e:
        print(f"❌ Email authentication failed. Check your Gmail App Password.")
        print(f"   Error: {e}")
        return False
    except Exception as e:
        print(f"❌ Failed to send email: {e}")
        return False


def send_daily_summary(
    changes_by_airport: Dict[str, Dict],
    no_change_airports: List[str],
    app_url: str = ""
) -> bool:
    """
    Send a daily summary email of all airport changes.

    Args:
        changes_by_airport: Dict mapping airport code to change data
        no_change_airports: List of airport codes with no changes
        app_url: URL to the web app

    Returns:
        True if email sent successfully, False otherwise
    """
    if not is_email_configured():
        print("Email alerts not configured.")
        return False

    config = get_email_config()

    total_airports_with_changes = len(changes_by_airport)

    if total_airports_with_changes == 0:
        subject = "✅ Airport Diagram Check: No changes detected"
    else:
        subject = f"🛫 Airport Diagram Check: {total_airports_with_changes} airport(s) have changes"

    # Build plain text body
    body_text = f"""
Daily Airport Diagram Check Summary
====================================

Date: {datetime.now().strftime('%Y-%m-%d')}
Airports checked: {len(changes_by_airport) + len(no_change_airports)}
Airports with changes: {total_airports_with_changes}

"""

    if changes_by_airport:
        body_text += "CHANGES DETECTED:\n"
        body_text += "-" * 40 + "\n"
        for airport, data in changes_by_airport.items():
            taxiway_count = len(data.get('taxiway_changes', []))
            runway_count = len(data.get('runway_changes', []))
            body_text += f"\n{airport}:\n"
            if taxiway_count:
                body_text += f"  • {taxiway_count} taxiway change(s)\n"
            if runway_count:
                body_text += f"  • {runway_count} runway change(s)\n"

    if no_change_airports:
        body_text += f"\nNO CHANGES: {', '.join(no_change_airports)}\n"

    if app_url:
        body_text += f"\nView details: {app_url}\n"

    # Create and send the message
    msg = MIMEText(body_text, 'plain')
    msg['Subject'] = subject
    msg['From'] = config['gmail_address']
    msg['To'] = config['recipient_email']

    try:
        with smtplib.SMTP_SSL('smtp.gmail.com', 465) as server:
            server.login(config['gmail_address'], config['gmail_password'])
            server.send_message(msg)

        print(f"✅ Daily summary email sent to {config['recipient_email']}")
        return True

    except Exception as e:
        print(f"❌ Failed to send daily summary: {e}")
        return False


# For testing
if __name__ == "__main__":
    print("Testing email configuration...")

    if is_email_configured():
        print("✅ Email is configured")

        # Send a test alert
        test_result = send_change_alert(
            airport_code="TEST",
            old_cycle="2601",
            new_cycle="2602",
            taxiway_changes=[
                {"change_type": "ADDED", "designator": "Y", "description": "New taxiway 'Y' added"},
                {"change_type": "REMOVED", "designator": "Z", "description": "Taxiway 'Z' removed"}
            ],
            runway_changes=[
                {"change_type": "LENGTH_CHANGED", "designator": "10/28", "description": "Runway 10/28 extended by 299 ft (7200 → 7499 ft)"}
            ],
            app_url="http://localhost:5000"
        )

        if test_result:
            print("✅ Test email sent successfully!")
        else:
            print("❌ Test email failed")
    else:
        print("❌ Email not configured. Set these environment variables:")
        print("   - GMAIL_ADDRESS")
        print("   - GMAIL_APP_PASSWORD")
        print("   - ALERT_RECIPIENT_EMAIL")
