import requests
import json
import time
import subprocess
import logging
import os
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.image import MIMEImage
from datetime import datetime

class SignalEmailBridge:
    """Bridge for forwarding Signal messages to email.
    
    This class connects to a Signal REST API, monitors for incoming messages,
    and forwards them to a specified email address including any attachments.
    It handles downloading attachments, formatting email content, and sending
    via msmtp.
    """
    def __init__(self, api_url: str, phone_number: str, email_to: str, email_from: str):
        """Initialize the Signal to Email bridge.
        
        Args:
            api_url: URL of the Signal REST API endpoint
            phone_number: Signal phone number to monitor for messages
            email_to: Destination email address for forwarded messages
            email_from: Sender email address to use in forwarded messages
        """
        self.api_url = api_url.rstrip('/')
        self.phone_number = phone_number
        self.email_to = email_to
        self.email_from = email_from
        
        # Setup logging
        logging.basicConfig(
            level=logging.INFO,
            format='%(asctime)s - %(levelname)s - %(message)s'
        )
        self.logger = logging.getLogger(__name__)

    def download_attachment(self, attachment_id: str) -> bytes:
        """Download attachment from Signal REST API"""
        try:
            response = requests.get(f"{self.api_url}/v1/attachments/{attachment_id}")
            response.raise_for_status()
            return response.content
        except Exception as e:
            self.logger.error(f"Failed to download attachment {attachment_id}: {e}")
            return None

    def send_email_with_attachments(self, subject: str, body: str, attachments=None):
        """Send email with attachments using msmtp"""
        msg = MIMEMultipart()
        msg['Subject'] = subject
        msg['From'] = self.email_from
        msg['To'] = self.email_to

        # Add text body
        msg.attach(MIMEText(body))

        # Add attachments if any
        if attachments:
            for attachment_data in attachments:
                try:
                    # Download attachment from Signal server
                    attachment_id = attachment_data.get('id')
                    content_type = attachment_data.get('contentType', '')
                    filename = attachment_data.get('filename', 'attachment')
                    
                    content = self.download_attachment(attachment_id)
                    if content:
                        # Handle images
                        if content_type.startswith('image/'):
                            img = MIMEImage(content)
                            img.add_header('Content-Disposition', 'attachment', filename=filename)
                            msg.attach(img)
                            self.logger.info(f"Attached image: {filename}")
                except Exception as e:
                    self.logger.error(f"Failed to process attachment: {e}")

        try:
            msmtp = subprocess.Popen(
                ['msmtp', '--read-envelope-from', self.email_to],
                stdin=subprocess.PIPE
            )
            msmtp.communicate(msg.as_bytes())
            if msmtp.returncode != 0:
                raise Exception(f"msmtp returned {msmtp.returncode}")
        except Exception as e:
            self.logger.error(f"Failed to send email: {e}")
            return False
        return True

    def receive_messages(self):
        """Fetch new messages from Signal REST API"""
        try:
            response = requests.get(f"{self.api_url}/v1/receive/{self.phone_number}")
            response.raise_for_status()
            messages = response.json()
            
            if messages:
                self.logger.debug(f"Received messages: {json.dumps(messages, indent=2)}")
            
            return messages
        except Exception as e:
            self.logger.error(f"Failed to receive messages: {e}")
            return None

    def process_message(self, message):
        """Process a single message and forward to email"""
        try:
            envelope = message.get('envelope', {})
            source_number = envelope.get('sourceNumber', 'Unknown')
            source_name = envelope.get('sourceName', '')
            timestamp = envelope.get('timestamp', 0)
            data_message = envelope.get('dataMessage', {})
            
            # Extract message content and attachments
            content = data_message.get('message', '')
            attachments = data_message.get('attachments', [])

            # Skip if there's no content AND no attachments
            if not content and not attachments:
                return

            # Format email subject and body
            date = datetime.fromtimestamp(timestamp/1000).strftime('%Y-%m-%d %H:%M:%S')
            subject = f"Signal Message from {source_name} ({source_number}) at {date}" if source_name else f"Signal Message from {source_number} at {date}"
            
            body = f"""
From: {f"{source_name} ({source_number})" if source_name else source_number}
Time: {date}

Message:
{content if content else '<no message>'}

Attachments:
"""
            if attachments:
                for idx, att in enumerate(attachments, 1):
                    body += f"[{idx}] Type: {att.get('contentType', 'unknown')}\n"
                    body += f"    Size: {att.get('size', 'unknown')} bytes\n"
            else:
                body += "<no attachments>"
            
            # Send email with attachments
            if self.send_email_with_attachments(subject, body, attachments):
                self.logger.info(
                    f"Forwarded message from {source_name} ({source_number}) "
                    f"({'with text' if content else 'no text'}, "
                    f"{len(attachments)} attachments)"
                )
            
        except Exception as e:
            self.logger.error(f"Failed to process message: {e}")
            self.logger.error(f"Message content: {json.dumps(message, indent=2)}")

    def run(self, poll_interval: int = 5):
        """Main loop to poll for messages"""
        self.logger.info("Starting Signal to Email bridge...")
        
        while True:
            try:
                messages = self.receive_messages()
                if messages:
                    for message in messages:
                        self.process_message(message)
                
                time.sleep(poll_interval)
                
            except KeyboardInterrupt:
                self.logger.info("Shutting down...")
                break
            except Exception as e:
                self.logger.error(f"Error in main loop: {e}")
                time.sleep(poll_interval)

if __name__ == "__main__":
    # Configuration
    bridge = SignalEmailBridge(
        api_url="http://localhost:8080",
        phone_number='+31612345678',
        email_to="your.name@email.com",
        email_from="signal@local"
    )
    
    # Start the bridge
    bridge.run()