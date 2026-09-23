"""All authenticated data APIs (registered directly onto the Flask app).

Split across focused modules for readability; every handler verifies the
session user and applies CSRF protection to state-changing requests.
"""


def register_data_routes(app) -> None:
    from routes.api_misc import register as register_misc
    from routes.api_profile_skills import register as register_profile_skills
    from routes.api_resumes import register as register_resumes
    from routes.api_roadmap import register as register_roadmap

    register_profile_skills(app)
    register_resumes(app)
    register_roadmap(app)
    register_misc(app)
