"""
EXAMPLE service - a template you can copy when building a new service.

To make your own:
  1. Copy this whole EXAMPLE folder and rename it to whatever you like
     (the folder name is purely organisational; users invoke services
     by an entry in the ALIASES list below, not by the folder name).
  2. Rename the class and update ALIASES.
  3. Implement the abstract methods get_titles, get_tracks, license.
  4. Edit config.yaml with the endpoint URLs and any per-service config
     your code needs (you can reach it as self.config inside the class).
"""
import click

from playvine.services.BaseService import BaseService


class EXAMPLE(BaseService):
    """
    A skeleton service. Replace EVERY method body with the real logic for
    your target streaming service. The framework will call into you in
    this order during a download run:

        get_titles()  -> get_tracks(title)  -> certificate()  -> license()
    """

    # CLI tags this service responds to. The first entry is conventionally
    # the short canonical tag (uppercase). Case-insensitive lookup.
    ALIASES = ["EX", "example"]

    # Optional: regex(es) used to pull a title id out of a URL or string.
    # If you do not need URL parsing, set this to an empty list.
    TITLE_RE = [
        r"^(?P<id>[A-Za-z0-9]+)$",
    ]

    @staticmethod
    @click.command(name="EXAMPLE", short_help="Skeleton service for reference")
    @click.argument("title", type=str)
    @click.pass_context
    def cli(ctx, **kwargs):
        return EXAMPLE(ctx, **kwargs)

    def __init__(self, ctx, **kwargs):
        super().__init__(ctx, **kwargs)
        # Service-specific state goes here. self.config, self.cookies,
        # self.credentials, self.session, self.log, self.title are all
        # set up by BaseService.__init__ already.

    def get_titles(self):
        raise NotImplementedError("EXAMPLE: implement get_titles()")

    def get_tracks(self, title):
        raise NotImplementedError("EXAMPLE: implement get_tracks(title)")

    def get_chapters(self, title):
        return []

    def certificate(self, **kwargs):
        # Return None to use the common Widevine privacy certificate.
        # Override if your service has its own service certificate.
        return None

    def license(self, challenge, **kwargs):
        raise NotImplementedError("EXAMPLE: implement license(challenge, ...)")
