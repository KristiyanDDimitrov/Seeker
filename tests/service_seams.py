"""Services a test builds over another service's own parts."""
from seeker.soulseek.download_service import DownloadService
from seeker.soulseek.review_service import ReviewService


def review_service_for(service: DownloadService) -> ReviewService:
    """The ReviewService `Application` would pair with `service`: same
    database, repositories and placement, and slskd reached through
    `service.soulseek`."""
    return ReviewService(
        service.database,
        lambda: service.soulseek,
        service.placement,
        service.tracks,
        service.locations,
        service.download_requests,
        service.track_matches,
        service.local_files,
        service.soulseek_review_candidates,
        service.rejections,
    )
