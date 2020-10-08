# Copyright 2020 Google LLC
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#      http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

# -- Path setup --------------------------------------------------------------

import os
import sys

sys.path.insert(0, os.path.abspath('..'))

# -- Project information -----------------------------------------------------

project = 'Refex'
copyright = '2020, Google LLC'
author = 'Devin Jeanpierre'

# -- General configuration ---------------------------------------------------

extensions = [
    'sphinx.ext.autodoc',
    'sphinx.ext.intersphinx',
    'sphinx.ext.napoleon',
    'm2r',
]

intersphinx_mapping = {
    'python': ('https://docs.python.org/3', None),
    'attrs': ('https://www.attrs.org/en/stable/', None),
    'asttokens': ('https://asttokens.readthedocs.io/en/latest/', None),
}

templates_path = ['_templates']

exclude_patterns = ['_build', 'Thumbs.db', '.DS_Store']

# -- Options for HTML output -------------------------------------------------

html_theme = 'sphinx_rtd_theme'
html_logo = '_static/logo.svg'
html_favicon = '_static/logo.ico'
html_css_files = [
    'customize.css',
]

globaltoc_includehidden = True
add_module_names = False
autodoc_member_order = 'bysource'

html_theme_options = {
    'includehidden': True,
    'style_nav_header_background': '#e64a19',
    'logo_only': False,
}

html_static_path = ['_static']
