# Copyright (C) 2026 Synopsys, Inc. and ANSYS, Inc. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
#
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
# http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""Opt-in lanes mode: share or isolate AEDT sessions across MCP clients.

Enabled with ``ansys-aedt-mcp --lanes``. Without that flag none of these
modules is imported and the server behaves exactly as before.

A lane is a long-lived ``ansys-aedt-mcp`` HTTP backend that owns at most one
AEDT session. A stdio routing proxy exposes the regular tools plus lane
management tools and forwards each call to the selected lane.
"""
