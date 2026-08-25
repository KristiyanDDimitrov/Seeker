import webbrowser

from seeker.config import SPOTIFY_CLIENT_ID, SPOTIFY_REDIRECT_URI
from seeker.spotify.auth import (
    build_authorization_url,
    exchange_code_for_token,
    generate_code_challenge,
    generate_code_verifier,
    generate_state,
)
from seeker.spotify.callback_server import wait_for_callback
from seeker.spotify.client import SpotifyClient


def main():
    print("Seeker is starting...")

    code_verifier = generate_code_verifier()
    code_challenge = generate_code_challenge(code_verifier)
    state = generate_state()

    authorization_url = build_authorization_url(
        client_id=SPOTIFY_CLIENT_ID,
        redirect_uri=SPOTIFY_REDIRECT_URI,
        state=state,
        code_challenge=code_challenge,
    )

    print("Opening Spotify authorization page...")

    webbrowser.open(authorization_url)

    code, returned_state, error = wait_for_callback()

    if error:
        raise RuntimeError(f"Spotify authorization failed: {error}")

    if returned_state != state:
        raise RuntimeError("Spotify state validation failed.")

    if not code:
        raise RuntimeError("Spotify did not return an authorization code.")

    token_data = exchange_code_for_token(
        client_id=SPOTIFY_CLIENT_ID,
        redirect_uri=SPOTIFY_REDIRECT_URI,
        code=code,
        code_verifier=code_verifier,
    )

    print("Spotify authorization successful.")
    print(f"Access token received: {bool(token_data.get('access_token'))}")

    access_token = token_data["access_token"]

    spotify = SpotifyClient(access_token)

    playlists = spotify.get_current_user_playlists()

    print()
    print("Your Spotify playlists:")
    print("-----------------------")

    for playlist in playlists:
        print(f"{playlist.name} ({playlist.track_count} tracks)")


if __name__ == "__main__":
    main()