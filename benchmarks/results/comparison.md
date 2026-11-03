Baseline: `916c196` | Current: `916c196-dirty`

| Metric | Baseline (median) | Current (median) | Change | Speed-up |
|---|---:|---:|---:|---:|
| concurrency.check_aedt_status_x4 | 10.13 s | 17 ms | -100% | 586.4x |
| connect.check_aedt_installed | 946 ms | 958 ms | +1% | 1.0x |
| connect.check_aedt_status.connected | 4.74 s | 26 ms | -99% | 185.8x |
| connect.check_aedt_status.disconnected | 4.56 s | 107 ms | -98% | 42.7x |
| connect.clear_aedt | 190 ms | 202 ms | +6% | 0.9x |
| connect.connect_to_aedt | 4.55 s | 110 ms | -98% | 41.4x |
| connect.connect_to_aedt.reconnect | 4.54 s | 43 ms | -99% | 106.0x |
| connect.create_design | 95 ms | 93 ms | -2% | 1.0x |
| connect.disconnect_from_aedt | 222 ms | 220 ms | -1% | 1.0x |
| connect.disconnect_from_aedt.keep_open | 93 ms | 97 ms | +5% | 1.0x |
| connect.export_config | 474 ms | 500 ms | +5% | 0.9x |
| connect.get_model_info | 20 ms | 17 ms | -16% | 1.2x |
| connect.get_pyaedt_logs | 88 ms | 88 ms | -0% | 1.0x |
| connect.list_designs | 144 ms | 139 ms | -3% | 1.0x |
| connect.list_projects | 8 ms | 7 ms | -13% | 1.2x |
| connect.run_python_code.after_error | 11 ms | 12 ms | +5% | 1.0x |
| connect.run_python_code.create_project | 328 ms | 321 ms | -2% | 1.0x |
| connect.run_python_code.error | 9 ms | 11 ms | +25% | 0.8x |
| connect.run_python_code.followup_edit | 450 ms | 40 ms | -91% | 11.2x |
| connect.run_python_code.geometry | 780 ms | 779 ms | -0% | 1.0x |
| connect.save_project | 54 ms | 55 ms | +1% | 1.0x |
| connect.validate_design | 94 ms | 98 ms | +4% | 1.0x |
| connect.validate_design.repeat | 80 ms | 85 ms | +6% | 0.9x |
| launch.create_design | 6.77 s | 6.90 s | +2% | 1.0x |
| launch.disconnect_from_aedt.close | 9.73 s | 4.27 s | -56% | 2.3x |
| launch.launch_aedt | 7.87 s | 5.39 s | -32% | 1.5x |
| loop.max_ping.connect.check_aedt_installed | 223 ms | 236 ms | +6% | 0.9x |
| loop.max_ping.connect.check_aedt_status.connected | 7 ms | 25 ms | +276% | 0.3x |
| loop.max_ping.connect.check_aedt_status.disconnected | 4 ms | 3 ms | -22% | 1.3x |
| loop.max_ping.connect.clear_aedt | 128 ms | 140 ms | +9% | 0.9x |
| loop.max_ping.connect.connect_to_aedt | 4.55 s | 5 ms | -100% | 951.7x |
| loop.max_ping.connect.connect_to_aedt.reconnect | 4.54 s | 4 ms | -100% | 1140.0x |
| loop.max_ping.connect.create_design | 32 ms | 25 ms | -23% | 1.3x |
| loop.max_ping.connect.disconnect_from_aedt | 219 ms | 154 ms | -30% | 1.4x |
| loop.max_ping.connect.disconnect_from_aedt.keep_open | 90 ms | 90 ms | -0% | 1.0x |
| loop.max_ping.connect.export_config | 50 ms | 53 ms | +5% | 0.9x |
| loop.max_ping.connect.get_model_info | 20 ms | 16 ms | -17% | 1.2x |
| loop.max_ping.connect.get_pyaedt_logs | 27 ms | 26 ms | -4% | 1.0x |
| loop.max_ping.connect.list_designs | 33 ms | 26 ms | -21% | 1.3x |
| loop.max_ping.connect.list_projects | 6 ms | 7 ms | +4% | 1.0x |
| loop.max_ping.connect.run_python_code.after_error | 8 ms | 4 ms | -56% | 2.3x |
| loop.max_ping.connect.run_python_code.create_project | 254 ms | 248 ms | -2% | 1.0x |
| loop.max_ping.connect.run_python_code.error | 6 ms | 6 ms | +8% | 0.9x |
| loop.max_ping.connect.run_python_code.followup_edit | 98 ms | 5 ms | -95% | 18.2x |
| loop.max_ping.connect.run_python_code.geometry | 226 ms | 236 ms | +4% | 1.0x |
| loop.max_ping.connect.save_project | 29 ms | 31 ms | +5% | 1.0x |
| loop.max_ping.connect.validate_design | 17 ms | 26 ms | +60% | 0.6x |
| loop.max_ping.connect.validate_design.repeat | 26 ms | 25 ms | -6% | 1.1x |
| loop.max_ping.launch.create_design | 6.73 s | 6.81 s | +1% | 1.0x |
| loop.max_ping.launch.disconnect_from_aedt.close | 9.73 s | 2.05 s | -79% | 4.7x |
| loop.max_ping.launch.launch_aedt | 7.87 s | 235 ms | -97% | 33.4x |
| loop.max_ping_during_check_status | 4 ms | 5 ms | +33% | 0.7x |
| prompt.instructions_chars | 3,783 | 4,183 | +11% |  |
| prompt.tool_count | 22 | 22 | +0% |  |
| prompt.tool_schema_chars | 23,703 | 23,965 | +1% |  |
| protocol.get_prompt | 1 ms | 2 ms | +11% | 0.9x |
| protocol.list_tools | 3 ms | 3 ms | +3% | 1.0x |
| protocol.ping | 1 ms | 1 ms | +13% | 0.9x |
| protocol.read_toolsets | 1 ms | 2 ms | +12% | 0.9x |
| stability.failed_calls | 0.00 | 0.00 | +0% |  |
| startup.initialize | 2.88 s | 1.70 s | -41% | 1.7x |
| startup.process_count | 5.00 | 3.00 | -40% |  |
| startup.rss_mb | 349 MB | 145 MB | -59% |  |
| tool.check_aedt_installed | 4 ms | 4 ms | +4% | 1.0x |
| tool.check_aedt_status.disconnected | 4.44 s | 5 ms | -100% | 838.5x |
| tool.get_guidelines_for | 3 ms | 3 ms | +2% | 1.0x |
| tool.get_pyaedt_logs | 4 ms | 3 ms | -6% | 1.1x |
