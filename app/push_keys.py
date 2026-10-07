"""Makes a VAPID key pair: python -m app.push_keys. Put both lines in the server's settings."""

from app.push import generate_keys

if __name__ == "__main__":
    private, public = generate_keys()
    print(f"VAPID_PRIVATE_KEY={private}")
    print(f"VAPID_PUBLIC_KEY={public}")
