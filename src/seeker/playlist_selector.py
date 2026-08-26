from seeker.models.playlist import Playlist


def select_playlist(playlists: list[Playlist]) -> Playlist:
    if not playlists:
        raise RuntimeError("No Spotify playlists were found.")

    print()
    print("Your Spotify playlists:")
    print("-----------------------")

    for index, playlist in enumerate(playlists, start=1):
        print(
            f"{index}. {playlist.name} "
            f"({playlist.track_count} tracks)"
        )

    while True:
        selection = input("\nSelect a playlist: ")

        try:
            index = int(selection)
        except ValueError:
            print("Please enter a number.")
            continue

        if 1 <= index <= len(playlists):
            return playlists[index - 1]

        print(
            f"Please enter a number between 1 and {len(playlists)}."
        )