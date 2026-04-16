from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    database_url: str = "postgresql://sentinel:sentinel@127.0.0.1:5450/sentinel"
    nppes_api_url: str = "https://npiregistry.cms.hhs.gov/api/?version=2.1"
    leie_csv_url: str = "https://oig.hhs.gov/exclusions/downloadables/UPDATED.csv"
    census_geocoder_url: str = (
        "https://geocoding.geo.census.gov/geocoder/geographies/addressbatch"
    )

    # Houston-area ZIP codes to ingest
    target_zips: list[str] = [
        f"770{i:02d}" for i in range(100)
    ] + [
        "77301", "77302", "77303", "77304", "77338", "77339",  # Conroe/Humble
        "77401", "77459", "77478", "77479", "77489",  # Sugar Land/Bellaire
        "77502", "77503", "77504", "77505", "77506",  # Pasadena
        "77571", "77573", "77581", "77584", "77586",  # Pearland/League City
    ]

    # Taxonomy codes for high-risk provider types
    dme_taxonomy: str = "332B00000X"
    hha_taxonomy: str = "251E00000X"
    hospice_taxonomy: str = "251G00000X"

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8"}


settings = Settings()
