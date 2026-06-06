from scripts.check_public_surface import check


def test_public_surface_has_no_hidden_paths_or_public_package_leaks() -> None:
    assert check() == []
