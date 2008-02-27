# -*- coding: utf-8 -*-
#
# Copyright (C) 2004-2006 Edgewall Software
# Copyright (C) 2004 Oliver Rutherfurd
# All rights reserved.
#
# This software is licensed as described in the file COPYING, which
# you should have received as part of this distribution. The terms
# are also available at http://trac.edgewall.org/wiki/TracLicense.
#
# This software consists of voluntary contributions made by many
# individuals. For the exact contribution history, see the revision
# history and logs, available at http://trac.edgewall.org/log/.
#
# Author: Daniel Lundin
#         Oliver Rutherfurd (initial implementation)
#         Nuutti Kotivuori (role support)
#
# Trac support for reStructured Text, including a custom 'trac' directive
#
# 'trac' directive code by Oliver Rutherfurd, overhauled by cboos.
#
# Inserts `reference` nodes for TracLinks into the document tree.

__docformat__ = 'reStructuredText'

from distutils.version import StrictVersion
import re
try:
    from docutils import nodes
    from docutils.core import publish_parts
    from docutils.parsers import rst
    from docutils import __version__
    has_docutils = True
except ImportError:
    has_docutils = False

from trac.core import *
from trac.mimeview.api import IHTMLPreviewRenderer, content_to_unicode
from trac.util.html import Element, Markup
from trac.util.translation import _
from trac.web.href import Href
from trac.wiki.api import WikiSystem
from trac.wiki.formatter import WikiProcessor, Formatter, extract_link

class ReStructuredTextRenderer(Component):
    """
    Renders plain text in reStructuredText format as HTML.
    """
    implements(IHTMLPreviewRenderer)

    def get_quality_ratio(self, mimetype):
        if mimetype == 'text/x-rst':
            return 8
        return 0

    def render(self, context, mimetype, content, filename=None, rev=None):
        global has_docutils
        if not has_docutils:
            raise TracError(_('Docutils not found'))
        if StrictVersion(__version__) < StrictVersion('0.3.9'):
            raise TracError(_('Docutils version >= %(version)s required, '
                              '%(found)s found', version='0.3.9',
                              found=__version__))

        def trac_get_reference(rawtext, target, text):
            fulltext = text and target+' '+text or target
            link = extract_link(self.env, context, fulltext)
            uri = None
            missing = False
            if isinstance(link, Element):
                linktext = Markup(link).striptags()
                # the following is a bit hackish, but it takes into account:
                #  - an eventual trailing '?' for missing wiki pages
                #  - space eventually introduced due to split_page_names option
                if linktext.rstrip('?').replace(' ', '') != target:
                    text = linktext
                uri = link.attrib.get('href', '')
                missing = 'missing' in link.attrib.get('class', '')
            else:
                uri = context.href.wiki(target)
                missing = not WikiSystem(self.env).has_page(target)
            if uri:                    
                reference = nodes.reference(rawtext, text or target)
                reference['refuri']= uri
                if missing:
                    reference.set_class('missing')
                return reference
            return None

        def trac(name, arguments, options, content, lineno,
                 content_offset, block_text, state, state_machine):
            """Inserts a `reference` node into the document 
            for a given `TracLink`_, based on the content 
            of the arguments.

            Usage::

              .. trac:: target [text]

            ``target`` may be any `TracLink`_, provided it doesn't
            embed a space character (e.g. wiki:"..." notation won't work).

            ``[text]`` is optional.  If not given, ``target`` is
            used as the reference text.

            .. _TracLink: http://trac.edgewall.org/wiki/TracLinks
            """
            link = arguments[0]
            if len(arguments) == 2:
                text = arguments[1]
            else:
                text = None
            reference = trac_get_reference(block_text, link, text)
            if reference:
                p = nodes.paragraph()
                p += reference
                return p
            # didn't find a match (invalid TracLink),
            # report a warning
            warning = state_machine.reporter.warning(
                    '%s is not a valid TracLink' % (arguments[0]),
                    nodes.literal_block(block_text, block_text),
                    line=lineno)
            return [warning]

        def trac_role(name, rawtext, text, lineno, inliner, options={},
                      content=[]):
            args  = text.split(" ",1)
            link = args[0]
            if len(args)==2:
                text = args[1]
            else:
                text = None
            reference = trac_get_reference(rawtext, link, text)
            if reference:
                return [reference], []
            warning = nodes.warning(None, nodes.literal_block(text,
                'WARNING: %s is not a valid TracLink' % rawtext))
            return warning, []

        # 1 required arg, 1 optional arg, spaces allowed in last arg
        trac.arguments = (1,1,1)
        trac.options = None
        trac.content = None
        rst.directives.register_directive('trac', trac)
        rst.roles.register_local_role('trac', trac_role)

        # The code_block could is taken from the leo plugin rst2
        def code_formatter(language, text):
            processor = WikiProcessor(Formatter(self.env, context), language)
            html = processor.process(text)
            raw = nodes.raw('', html, format='html')
            return raw
        
        def code_role(name, rawtext, text, lineno, inliner, options={},
                      content=[]):
            language = options.get('language')
            if not language:
                args  = text.split(':', 1)
                language = args[0]
                if len(args) == 2:
                    text = args[1]
                else:
                    text = ''
            reference = code_formatter(language, text)
            return [reference], []
        
        def code_block(name, arguments, options, content, lineno,
                       content_offset, block_text, state, state_machine):
            """
            Create a code-block directive for docutils.

            Usage: .. code-block:: language

            If the language can be syntax highlighted it will be.
            """
            language = arguments[0]
            text = '\n'.join(content)        
            reference = code_formatter(language, text)
            return [reference]

        # These are documented
        # at http://docutils.sourceforge.net/spec/howto/rst-directives.html.
        code_block.arguments = (
            1, # Number of required arguments.
            0, # Number of optional arguments.
            0) # True if final argument may contain whitespace.
    
        # A mapping from option name to conversion function.
        code_role.options = code_block.options = {
            'language' :
            rst.directives.unchanged # Return the text argument, unchanged
        }
        code_block.content = 1 # True if content is allowed.
        # Register the directive with docutils.
        rst.directives.register_directive('code-block', code_block)
        rst.roles.register_local_role('code-block', code_role)

        _inliner = rst.states.Inliner()
        _parser = rst.Parser(inliner=_inliner)
        content = content_to_unicode(self.env, content, mimetype)
        parts = publish_parts(content, writer_name='html', parser=_parser,
                              settings_overrides={'halt_level': 6, 
                                                  'file_insertion_enabled': 0, 
                                                  'raw_enabled': 0})
        return parts['html_body']
