import os
import uuid
import boto3
from io import BytesIO

R2_ACCESS_KEY_ID = os.getenv("R2_ACCESS_KEY_ID")
R2_SECRET_ACCESS_KEY = os.getenv("R2_SECRET_ACCESS_KEY")
R2_BUCKET = os.getenv("R2_BUCKET")
R2_ENDPOINT = os.getenv("R2_ENDPOINT")
R2_PUBLIC_URL = os.getenv("R2_PUBLIC_URL")

s3 = boto3.client(
    "s3",
    endpoint_url=R2_ENDPOINT,
    aws_access_key_id=R2_ACCESS_KEY_ID,
    aws_secret_access_key=R2_SECRET_ACCESS_KEY,
)

def upload_image(image):
    filename = f"{uuid.uuid4()}.png"

    buffer = BytesIO()
    image.save(buffer, format="PNG")
    buffer.seek(0)

    s3.upload_fileobj(
        buffer,
        R2_BUCKET,
        filename,
        ExtraArgs={"ContentType": "image/png"},
    )

    return f"{R2_PUBLIC_URL}/{filename}"
