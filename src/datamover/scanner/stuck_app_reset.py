import logging
from pathlib import Path
from typing import Optional, Set, Tuple

logger = logging.getLogger(__name__)


def get_app_name_from_path(file_path: Path) -> Optional[str]:
    """
    Extracts the App Name from a filename like 'APPNAME-timestamp.ext'.
    The App Name is assumed to be the part of the filename before the first hyphen.
    (As per Glossary in requirements doc - stuck_files.md)
    """
    name: str = file_path.name
    head, sep, _ = name.partition("-")
    if head and sep:
        return head

    # If there's no hyphen (or it starts with one), warn and return None
    logger.warning(
        "Could not extract App Name (part before first hyphen) from filename: %r",
        name,
    )
    return None


def determine_app_restart_actions(
    current_stuck_file_paths: Set[Path],
    previously_signaled_apps: Set[str],
    restart_trigger_directory: Path,
) -> Tuple[Set[Path], Set[str]]:
    """
    Determines .restart files to create for newly stuck applications and
    provides the updated set of all currently stuck application names.

    This function is pure and aligns with FR1, FR2, FR4, and NFR3.

    Args:
        current_stuck_file_paths: A set of Path objects for all files
                                  currently identified as Stuck Files. (FR1.1)
        previously_signaled_apps: A set of App Names for which a restart trigger
                                  was already issued and is being tracked in memory. (FR2.1)
        restart_trigger_directory: The directory where .restart files (Restart Trigger Files)
                                   should be notionally created. This function does not
                                   create files, only determines their paths.

    Returns:
        A tuple containing:
        - restart_trigger_files_to_create (Set[Path]):
            Set of Path objects for .restart files that should be created for
            applications that are newly considered stuck.
        - Current_stuck_apps (Set[str]):
            Set of all unique App Names derived from `current_stuck_file_paths`.
            This set should be used as `previously_signaled_apps` in the
            next processing cycle. (FR2.4)
    """
    # FR1.2: Derive App Set
    current_stuck_apps: Set[str] = set()
    for path in current_stuck_file_paths:
        app_name: Optional[str] = get_app_name_from_path(path)
        if app_name:
            current_stuck_apps.add(app_name)

    # FR2.2: Newly Stuck
    newly_stuck_apps: Set[str] = current_stuck_apps - previously_signaled_apps

    restart_trigger_files_to_create: Set[Path] = set()
    if newly_stuck_apps:
        logger.info(
            "Newly stuck applications identified for restart signal: %s",
            ", ".join(sorted(list(newly_stuck_apps))),
        )
        for app_name_to_signal in newly_stuck_apps:
            # FR2.3 (determines path, creation handled by caller)
            restart_filename: str = f"{app_name_to_signal}.restart"  # Use .restart
            restart_file_path: Path = restart_trigger_directory / restart_filename
            restart_trigger_files_to_create.add(restart_file_path)
            logger.debug(
                "Determined restart trigger file '%s' for newly stuck app '%s'",
                restart_file_path,
                app_name_to_signal,
            )
    elif current_stuck_apps:  # Apps are stuck, but not newly stuck
        logger.debug(
            "No new applications require a restart signal. "
            "Currently stuck applications (%s) were already signaled or have no valid App Name.",
            ", ".join(sorted(list(current_stuck_apps))),
        )
    else:  # No apps are stuck
        logger.debug("No applications currently stuck. No restart signals needed.")

    # FR2.4: The second element of the tuple is effectively this update for the caller
    # FR4.1 & FR4.2 are implicitly handled: if an app is not in current_stuck_file_paths,
    # it won't be in current_stuck_apps. Thus, when current_stuck_apps is returned
    # to become previously_signaled_apps for the next cycle, the unstuck app is removed.
    return restart_trigger_files_to_create, current_stuck_apps
