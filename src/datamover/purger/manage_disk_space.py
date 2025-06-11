import logging
from pathlib import Path

from datamover.file_functions.fs_mock import FS
from datamover.purger.format_size_human_readable import format_size_human_readable
from datamover.purger.process_files_for_deletion import process_files_for_deletion
from datamover.purger.scan_and_sort_files import scan_and_sort_files

logger = logging.getLogger(__name__)


def manage_disk_space(
    *,
    work_dir_path: Path,
    uploaded_dir_path: Path,
    fs: FS,
    total_disk_capacity_bytes: int,
    target_disk_usage_percent: float = 0.80,
) -> None:
    """
    Manages disk space by deleting the oldest files to keep usage below a target.

    Deletion order:
    1. Oldest files from `uploaded_dir_path`.
    2. If necessary, oldest files from `work_dir_path`.

    Args:
        work_dir_path: Path to the directory where new files are staged.
        uploaded_dir_path: Path to the directory where uploaded files are moved.
        fs: Filesystem abstraction instance (as per your FS dataclass).
        total_disk_capacity_bytes: Total capacity of the disk in bytes.
        target_disk_usage_percent: The target disk usage (e.g., 0.80 for 80%).
    """
    logger.info(
        "Starting disk space management. Target: < %.0f%% of %s.",
        target_disk_usage_percent * 100,
        format_size_human_readable(total_disk_capacity_bytes),
    )

    # 1. Scan directories and sort files
    uploaded_files_sorted, scan_uploaded_ok = scan_and_sort_files(
        uploaded_dir_path, fs, "uploaded"
    )
    work_files_sorted, scan_work_ok = scan_and_sort_files(work_dir_path, fs, "work")

    if not scan_work_ok and not scan_uploaded_ok:
        logger.error("Both directory scans failed. Aborting cleanup.")
        return

    size_of_uploaded_files = sum(f.size for f in uploaded_files_sorted)
    size_of_work_files = sum(f.size for f in work_files_sorted)
    current_total_used_space_bytes = size_of_uploaded_files + size_of_work_files

    if (
        not work_files_sorted
        and not uploaded_files_sorted
        and scan_work_ok
        and scan_uploaded_ok
    ):
        logger.info(
            "Both directories successfully scanned and are empty. No files to manage."
        )
        return

    # 2. Calculate overall deletion needs
    target_bytes_to_keep_on_disk_overall = int(
        total_disk_capacity_bytes * target_disk_usage_percent
    )

    logger.info(
        "Current total used space: %s (Uploaded: %s, Work: %s).",
        format_size_human_readable(current_total_used_space_bytes),
        format_size_human_readable(size_of_uploaded_files),
        format_size_human_readable(size_of_work_files),
    )
    logger.info(
        "Target space to keep on disk (max overall): %s.",
        format_size_human_readable(target_bytes_to_keep_on_disk_overall),
    )

    if current_total_used_space_bytes <= target_bytes_to_keep_on_disk_overall:
        logger.info("Current disk usage is within target. No files need to be deleted.")
        return

    overall_bytes_to_delete_target = (
        current_total_used_space_bytes - target_bytes_to_keep_on_disk_overall
    )
    logger.info(
        "Need to delete at least %s overall to reach target.",
        format_size_human_readable(overall_bytes_to_delete_target),
    )

    total_bytes_deleted_this_session = 0

    # 3. Process UPLOADED files first
    target_bytes_to_keep_in_uploaded_dir = max(
        0, size_of_uploaded_files - overall_bytes_to_delete_target
    )
    bytes_deleted_from_uploaded = process_files_for_deletion(
        files_to_consider=uploaded_files_sorted,
        fs=fs,
        directory_description="uploaded directory",
        target_bytes_to_keep=target_bytes_to_keep_in_uploaded_dir,
    )
    total_bytes_deleted_this_session += bytes_deleted_from_uploaded

    # 4. Calculate remaining deletion need and process WORK files
    bytes_still_needing_deletion = (
        overall_bytes_to_delete_target - total_bytes_deleted_this_session
    )

    if bytes_still_needing_deletion > 0 and work_files_sorted:
        logger.info(
            "Still need to delete %s. Processing work directory.",
            format_size_human_readable(bytes_still_needing_deletion),
        )
        target_bytes_to_keep_in_work_dir = max(
            0, size_of_work_files - bytes_still_needing_deletion
        )
        bytes_deleted_from_work = process_files_for_deletion(
            files_to_consider=work_files_sorted,
            fs=fs,
            directory_description="work directory",
            target_bytes_to_keep=target_bytes_to_keep_in_work_dir,
        )
        total_bytes_deleted_this_session += bytes_deleted_from_work
    elif bytes_still_needing_deletion > 0:
        logger.info(
            "Still need to delete %s, but no files available in work directory.",
            format_size_human_readable(bytes_still_needing_deletion),
        )

    # 5. Final summary
    logger.info("Disk space management session finished.")
    logger.info(
        "Total bytes actually deleted in this session: %s.",
        format_size_human_readable(total_bytes_deleted_this_session),
    )

    final_estimated_used_space_bytes = (
        current_total_used_space_bytes - total_bytes_deleted_this_session
    )

    if total_disk_capacity_bytes > 0:
        final_estimated_usage_percent = (
            final_estimated_used_space_bytes / total_disk_capacity_bytes
        ) * 100
        logger.info(
            "Estimated current disk usage: %s (%.1f%%).",
            format_size_human_readable(final_estimated_used_space_bytes),
            final_estimated_usage_percent,
        )
    else:
        logger.info(
            "Estimated current disk usage: %s (total capacity was zero or not provided).",
            format_size_human_readable(final_estimated_used_space_bytes),
        )

    deficit_after_deletions = (
        final_estimated_used_space_bytes - target_bytes_to_keep_on_disk_overall
    )

    if deficit_after_deletions > 0:
        logger.warning(
            "Disk cleanup finished, but may still be %s above the target. "
            "This can occur if remaining files are very large, all deletable "
            "files were processed, or deletions failed.",
            format_size_human_readable(deficit_after_deletions),
        )
    elif total_bytes_deleted_this_session > 0:
        logger.info("Successfully brought disk usage to target or below.")
    else:
        if current_total_used_space_bytes <= target_bytes_to_keep_on_disk_overall:
            logger.info(
                "No files were deleted in this session as target was already met."
            )
        else:
            logger.info(
                "No files were actually deleted in this session, though deletion might have been needed."
            )
