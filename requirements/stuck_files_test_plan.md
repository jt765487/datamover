Please make sure we reverence back to the test plan in the new tests - please create the test code

Test Plan: DoSingleCycle - Stuck File & Restart Trigger Integration QA

Document Version: 1.0
Date: 2025-05-26
Purpose: To define test cases for verifying the functionality of the DoSingleCycle class, with a specific focus on its handling of stuck application detection, state management of signaled applications, interaction with determine_app_restart_actions, and the creation of .restart trigger files as per requirements FR1-FR4 and NFR1-NFR3.

1. Prerequisites & Test Environment Setup:

    Target Class: datamover.scanner.stuck_app_reset.DoSingleCycle (conceptual path)
    Primary Method Under Test: process_one_cycle()
    Key Internal Methods Involved: _handle_scan_results_side_effects(), _create_restart_trigger_files()
    Test Framework: pytest (assumed)
    Dependencies to Mock:
        self.fs (Filesystem Abstraction): Mock fs.open() to control file creation outcomes and verify calls.
        self.lost_file_queue: Mock Queue.put() or safe_put to verify items are enqueued and to isolate stuck file logic.
        self.time_func, self.monotonic_func: Provide stable mock callables returning fixed or predictable time values.
        process_scan_results (Function from datamover.scanner.process_scan_results):
            Crucial Mocking Strategy: This function will be mocked to provide direct control over its outputs, primarily currently_stuck_active_paths.
            Mock Completeness: The mock for process_scan_results must return a complete tuple matching its signature: (next_file_states, removed_tracking_paths, currently_lost_paths, currently_stuck_active_paths). For tests focused on stuck files, next_file_states can be an empty dictionary, and removed_tracking_paths / currently_lost_paths can be empty sets, unless a specific test requires them to be populated (e.g., TC-DSC-10-Enhanced for ordering). This ensures that parts of process_one_cycle unrelated to the specific test focus do not cause errors due to incomplete mock data.
        scan_directory_and_filter (Function from datamover.file_functions.scan_directory_and_filter): May be mocked to return an empty list if process_scan_results is the primary mock target for controlling inputs.
        report_state_changes (Function from datamover.scanner.scan_reporting): To be mocked for TC-DSC-13 to verify call order.
    Constants: A test-scoped constant for the restart directory path, e.g., RESTART_DIR = Path("/test/restarts").
    Logging: Utilize caplog fixture to capture and assert log messages from MODULE_LOGGER_NAME = "datamover.scanner.stuck_app_reset".

2. Test Case Format:

Each test case will include:

    Test Case ID: e.g., TC-DSC-X
    Description: A brief explanation of the test's purpose.
    Initial State / Mocks: Specific setup for DoSingleCycle instance variables (like previously_signaled_stuck_apps) and behavior of mocked dependencies.
    Action: The call to instance.process_one_cycle(...) with relevant arguments.
    Expected Outcome: Assertions on:
        The state of instance.previously_signaled_stuck_apps after the cycle.
        Calls made to mocked objects (e.g., mock_fs.open with specific arguments, mock_lost_file_queue.put).
    Expected Key Logs: Verification of critical INFO, DEBUG, WARNING, or ERROR log messages.

3. Test Cases:

TC-DSC-1: Initialization of Stuck App State

    Description: Verify that previously_signaled_stuck_apps is initialized as an empty set upon DoSingleCycle instantiation.
    Initial State / Mocks: Standard instantiation of DoSingleCycle with necessary constructor mocks.
    Action: Create an instance of DoSingleCycle.
    Expected Outcome: instance.previously_signaled_stuck_apps == set().
    Expected Key Logs: The DoSingleCycle initialization log message.

TC-DSC-2: No Stuck Applications During Cycle

    Description: Test a cycle where process_scan_results identifies no "stuck active" files.
    Initial State / Mocks:
        instance.previously_signaled_stuck_apps = set().
        Mock process_scan_results to return (dict(), set(), set(), set()) (i.e., currently_stuck_active_paths = set()).
    Action: Call instance.process_one_cycle(current_file_states={}, previously_lost_paths=set(), previously_stuck_active_paths=set()).
    Expected Outcome:
        instance.previously_signaled_stuck_apps remains set().
        mock_fs.open is NOT called for any .restart files.
    Expected Key Logs:
        DEBUG: "No new restart triggers required..."
        DEBUG: "Updated previously_signaled_stuck_apps for next cycle: None"
        DEBUG (from determine_app_restart_actions): "No applications currently stuck..."

TC-DSC-3: New Single Stuck Application

    Description: Test a cycle where one application becomes newly stuck.
    Initial State / Mocks:
        instance.previously_signaled_stuck_apps = set().
        Mock process_scan_results to return (dict(), set(), set(), {Path("APP1-timestamp1.pcap")}).
    Action: Call instance.process_one_cycle(...).
    Expected Outcome:
        instance.previously_signaled_stuck_apps == {"APP1"}.
        mock_fs.open called once with (RESTART_DIR / "APP1.restart", "a").
    Expected Key Logs:
        INFO: "Identified 1 application(s) requiring a new restart trigger."
        INFO: "Successfully created/updated restart trigger file: /test/restarts/APP1.restart"
        DEBUG: "Updated previously_signaled_stuck_apps for next cycle: {'APP1'}"
        INFO (from determine_app_restart_actions): "Newly stuck applications identified... APP1"
        Negative Log Assertion: No ERROR or CRITICAL logs from MODULE_LOGGER_NAME.

TC-DSC-4: New Multiple Stuck Applications (Different Apps)

    Description: Test a cycle where multiple different applications become newly stuck.
    Initial State / Mocks:
        instance.previously_signaled_stuck_apps = set().
        Mock process_scan_results to return (dict(), set(), set(), {Path("APP1-ts1.pcap"), Path("APP2-ts1.pcap")}).
    Action: Call instance.process_one_cycle(...).
    Expected Outcome:
        instance.previously_signaled_stuck_apps == {"APP1", "APP2"}.
        mock_fs.open called for APP1.restart and APP2.restart (mode 'a'), in sorted order of filenames.
    Expected Key Logs: INFO: "Identified 2 application(s)...", INFO logs for successful creation of both files, DEBUG: "Updated previously_signaled_stuck_apps...".

TC-DSC-5: Multiple Stuck Files for the Same Newly Stuck App

    Description: Test a cycle where multiple files for the same application become newly stuck. Only one trigger file should be created for the app.
    Initial State / Mocks:
        instance.previously_signaled_stuck_apps = set().
        Mock process_scan_results to return (dict(), set(), set(), {Path("APP1-ts1.pcap"), Path("APP1-ts2.pcap")}).
    Action: Call instance.process_one_cycle(...).
    Expected Outcome:
        instance.previously_signaled_stuck_apps == {"APP1"}.
        mock_fs.open called once with (RESTART_DIR / "APP1.restart", "a").
    Expected Key Logs: INFO: "Identified 1 application(s)...", INFO log for successful creation of APP1.restart.

TC-DSC-6: Existing Stuck Application (No Re-trigger)

    Description: An application that was previously signaled remains stuck. No new trigger file should be created.
    Initial State / Mocks:
        instance.previously_signaled_stuck_apps = {"APP1"}.
        Mock process_scan_results to return (dict(), set(), set(), {Path("APP1-timestamp2.pcap")}).
    Action: Call instance.process_one_cycle(...).
    Expected Outcome:
        instance.previously_signaled_stuck_apps == {"APP1"}.
        mock_fs.open is NOT called for APP1.restart.
    Expected Key Logs: DEBUG: "No new restart triggers required...", DEBUG: "Updated previously_signaled_stuck_apps...".
        DEBUG (from determine_app_restart_actions): "No new applications require a restart signal...".

TC-DSC-7: Application Becomes Unstuck

    Description: A previously stuck and signaled application is no longer stuck. Its state should be cleared from previously_signaled_stuck_apps.
    Initial State / Mocks:
        instance.previously_signaled_stuck_apps = {"APP1"}.
        Mock process_scan_results to return (dict(), set(), set(), set()).
    Action: Call instance.process_one_cycle(...).
    Expected Outcome:
        instance.previously_signaled_stuck_apps == set().
        mock_fs.open is NOT called.
    Expected Key Logs: DEBUG: "No new restart triggers required...", DEBUG: "Updated previously_signaled_stuck_apps for next cycle: None".

TC-DSC-8: Application Re-Stuck After Being Unstuck (Multi-Cycle Simulation)

    Description: Verify FR4.3. An application is stuck, then unstuck, then stuck again, and should be re-signaled. This test involves multiple calls to process_one_cycle on the same instance.
    Cycle 1 (App Becomes Stuck):
        Initial State: instance.previously_signaled_stuck_apps = set().
        Mock process_scan_results to return: (dict(), set(), set(), {Path("APP1-ts1.pcap")}).
        Action: Call instance.process_one_cycle(...).
        Verify: instance.previously_signaled_stuck_apps == {"APP1"}, mock_fs.open called for APP1.restart. Clear mock calls/logs.
    Cycle 2 (App Becomes Unstuck):
        State: instance.previously_signaled_stuck_apps is {"APP1"}.
        Mock process_scan_results to return: (dict(), set(), set(), set()).
        Action: Call instance.process_one_cycle(...).
        Verify: instance.previously_signaled_stuck_apps == set(), mock_fs.open NOT called. Clear mock calls/logs.
    Cycle 3 (App Becomes Re-Stuck):
        State: instance.previously_signaled_stuck_apps is set().
        Mock process_scan_results to return: (dict(), set(), set(), {Path("APP1-ts2.pcap")}).
        Action: Call instance.process_one_cycle(...).
        Verify: instance.previously_signaled_stuck_apps == {"APP1"}, mock_fs.open called again for APP1.restart.

TC-DSC-9: Mixed Scenario (New, Existing, Unstuck Apps)

    Description: Test a complex cycle with a mix of app states: APP1 (existing stuck), APP2 (newly stuck), APP3 (was stuck, now unstuck).
    Initial State / Mocks:
        instance.previously_signaled_stuck_apps = {"APP1", "APP3"}.
        Mock process_scan_results to return (dict(), set(), set(), {Path("APP1-ts2.pcap"), Path("APP2-ts1.pcap")}).
    Action: Call instance.process_one_cycle(...).
    Expected Outcome:
        instance.previously_signaled_stuck_apps == {"APP1", "APP2"}.
        mock_fs.open called for APP2.restart (mode 'a').
        mock_fs.open NOT called for APP1.restart.
    Expected Key Logs: INFO log for signaling APP2, relevant DEBUG logs for state updates.

TC-DSC-10: Filesystem Errors During Trigger Creation & Ordering Guarantee (NFR2)

    Description: Test robustness when fs.open fails for some trigger files, ensuring other operations (like other restart file creations or lost file queuing) still proceed.
    Initial State / Mocks:
        instance.previously_signaled_stuck_apps = set().
        Mock process_scan_results to return:
            currently_stuck_active_paths = {Path("APP1-ts1.pcap"), Path("APPFAIL-ts1.pcap"), Path("APP2-ts1.pcap")}.
            currently_lost_paths = {Path("LOST1-ts1.log")} (to ensure _enqueue_lost_files has work).
            Other returns: (dict(), set()) for next_file_states and removed_tracking_paths.
        Configure mock_fs.open:
            Succeed for (RESTART_DIR / "APP1.restart", "a").
            Raise IOError("Disk full") for (RESTART_DIR / "APPFAIL.restart", "a").
            Succeed for (RESTART_DIR / "APP2.restart", "a").
        Mock self.lost_file_queue.put (or safe_put if used directly by the class) to track calls.
    Action: Call instance.process_one_cycle(current_file_states={}, previously_lost_paths=set(), previously_stuck_active_paths=set()).
    Expected Outcome:
        instance.previously_signaled_stuck_apps == {"APP1", "APPFAIL", "APP2"}.
        mock_fs.open called for APP1.restart (succeeds).
        mock_fs.open called for APPFAIL.restart (fails).
        mock_fs.open called for APP2.restart (succeeds).
        mock_lost_file_queue.put called with Path("LOST1-ts1.log").
    Expected Key Logs:
        INFO: "Identified 3 application(s)..."
        INFO: "Successfully created... APP1.restart"
        EXCEPTION: "Failed to create... APPFAIL.restart" with "Disk full".
        INFO: "Successfully created... APP2.restart"
        INFO: "Finished creating/updating 2..."
        WARNING: "Failed to create/update 1..."
        INFO: "...enqueuing 1 newly identified 'lost' files..."
        INFO: "...enqueued 'lost' file: LOST1-ts1.log"
        DEBUG: "Updated previously_signaled_stuck_apps..."

TC-DSC-11: Stuck Files with Invalid App Names

    Description: Ensure that if process_scan_results provides paths that result in invalid app names, only valid apps are processed for triggers.
    Initial State / Mocks:
        instance.previously_signaled_stuck_apps = set().
        Mock process_scan_results to return (dict(), set(), set(), {Path("APP1-ts1.pcap"), Path("INVALIDFILENAME.pcap"), Path("-anotherinvalid.log")}).
    Action: Call instance.process_one_cycle(...).
    Expected Outcome:
        instance.previously_signaled_stuck_apps == {"APP1"}.
        mock_fs.open called only for (RESTART_DIR / "APP1.restart", "a").
    Expected Key Logs:
        WARNING (from get_app_name_from_path via determine_app_restart_actions): for "INVALIDFILENAME.pcap" and "-anotherinvalid.log".
        INFO (from determine_app_restart_actions): "Newly stuck applications identified... APP1"
        INFO: "Identified 1 application(s) requiring a new restart trigger."
        INFO: Log for successful creation of APP1.restart.

TC-DSC-12: Restart Trigger Creation Fails Due to Missing Directory (NFR2)

    Description: Verify robust handling if fs.open fails because the restart trigger directory does not exist.
    Initial State / Mocks:
        instance.previously_signaled_stuck_apps = set().
        Mock process_scan_results to return (dict(), set(), set(), {Path("APP1-ts1.pcap")}).
        Configure mock_fs.open to raise FileNotFoundError("No such file or directory") when called for (RESTART_DIR / "APP1.restart", "a").
    Action: Call instance.process_one_cycle(...).
    Expected Outcome:
        instance.previously_signaled_stuck_apps == {"APP1"}.
        mock_fs.open called for APP1.restart.
    Expected Key Logs:
        INFO: "Identified 1 application(s)..."
        EXCEPTION: "Failed to create/update restart trigger file: /test/restarts/APP1.restart" with "No such file or directory".
        WARNING: "Failed to create/update 1 restart trigger file(s)..."
        DEBUG: "Updated previously_signaled_stuck_apps..."
        The overall cycle should complete without crashing.

TC-DSC-13: Verify Order of Side Effects in _handle_scan_results_side_effects

    Description: Ensure that report_state_changes, lost file enqueuing, and restart trigger file creation occur in the intended sequence.
    Initial State / Mocks:
        instance.previously_signaled_stuck_apps = set().
        Mock process_scan_results to return values that trigger all three side effects:
            currently_stuck_active_paths = {Path("APP1-ts1.pcap")}
            currently_lost_paths = {Path("LOST1-ts1.log")} (and ensure this results in newly_lost_paths = {Path("LOST1-ts1.log")} by setting previously_lost_paths=set() in process_one_cycle call)
            removed_tracking_paths = set() (or some value for report_state_changes)
            next_file_states = dict()
        Mock datamover.scanner.scan_reporting.report_state_changes as mock_report_state.
        Mock self._enqueue_lost_files as mock_enqueue_lost (or spy self.lost_file_queue.put).
        Mock self._create_restart_trigger_files as mock_create_triggers (or spy self.fs.open).
    Action: Call instance.process_one_cycle(current_file_states={}, previously_lost_paths=set(), previously_stuck_active_paths=set()).
    Expected Outcome (using unittest.mock.Mock.method_calls or similar):
        mock_report_state is called.
        mock_enqueue_lost (or self.lost_file_queue.put) is called.
        mock_create_triggers (or self.fs.open) is called.
        Verify they are called with expected high-level arguments if necessary.