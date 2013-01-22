#!/usr/bin/env python

import collections
import itertools
from genshi.input import HTML
from genshi.filters.html import HTMLSanitizer
from genshi.filters.transform import Transformer
from genshi.core import Stream
from cssselect import HTMLTranslator

class EnactException(Exception): pass
class TransformException(EnactException): pass

class Enact(object):
    """
    Enact is a CSS selector-based templating library.
    It is a rough Python port of Enlive (written in Clojure)
    """

    @staticmethod
    def page(file_path, *transform_list):
        """
        Perform transformations against the content stored in a file.
        Arguments:
            file_path - a string, the path (as passed to file()) to the file containing the HTML content
            *transform_list - a variable-len list, the transforms to perform on on the content
        Returns:
             - a string, the transformed content
        """
        with open(file_path) as f:
            document_str = f.read()
            return Enact.string(document_str, *transform_list)

    @staticmethod
    def string(document_str, *transform_list, **option_overrides):
        """
        Perform transformations against the contents of a string
        Arguments:
            document_str - a string, the document/str to perform transformations against
            *transform_list - a variable-len list, the transforms to perform on on the content
            **option_overrides - a variable-len keyword arg list, the formatting/processing options to use
        Returns:
             - a string, the transformed content
        """
        if not document_str:
            return document_str
        if len(transform_list) % 2:
            raise EnactException("Every transform selection needs exactly one arg.  You passed: " + str(transform_list))
        # Get formatting/processing options
        doctype = option_overrides.get("doctype", "html5")
        # Process the transforms
        htmldoc = Enact.ensureHTML(document_str)
        transforms = zip(transform_list[0::2], transform_list[1::2])
        translator = HTMLTranslator() # this is done for performance only
        replace_dict = {}
        # Build up the replacement dict: {original_str: substitution_str}
        for css_selector, action_list in transforms:
            selection = Enact.cssSelection(css_selector, htmldoc, translator)
            action_pairs = zip(action_list[0::2], action_list[1::2])
            transformed_selection = reduce(Enact.applyTransform, action_pairs, selection)
            replace_dict[selection.render('html')] = transformed_selection.render('html')
        # Reduce the selection-based transforms that were made against the original content,
        #   generating the final transformed template/content
        return reduce(lambda result,(substring,replacement): result.replace(substring, replacement),
                        sorted(replace_dict.items(), key=lambda(k,v): len(k), reverse=True),
                        htmldoc.render('html', doctype=doctype))

    @staticmethod
    def cssToXpath(css_selector, translator=None):
        if not translator:
            translator = HTMLTranslator()
        return translator.css_to_xpath(css_selector)

    @staticmethod
    def cssSelection(css_selector, html_document, translator=None):
        """
        Return an HTML doc of the CSS-selected section
        """
        html_document = Enact.ensureHTML(html_document)
        xpath_expr = Enact.cssToXpath(css_selector, translator)
        return Enact.ensureHTML(html_document.select(xpath_expr), True)

    @staticmethod
    def applyTransform(trans_selection, action_pair):
        """
        Apply a transformation to an HTML doc, most likely the result of a cssSelection
        Arguments:
            trans_selection - an HTML doc, the HTML doc selection you're transforming
            action-pair - a tuple, (fn, data) - the transforming function, and any data that function requires
        Returns:
             - an HTML doc - the transformed doc
        Notes:
            fn MUST ALWAYS expect a selection object and return a selection object (or string)
        """
        fn, trans_data = action_pair
        transformed = fn(trans_selection, trans_data)
        try:
            return Enact.ensureHTML(transformed, True)
        except:
            raise TransformException("Your transformation function MUST return a string or a selection obj (HTML obj) - " + fn.__name__)

    @staticmethod
    def ensureHTML(obj, recast_stream=False):
        """
        Normalize various data types into a uniform HTML-doc type
        """
        # This is terrible...
        # TODO - we need to be smarter about this dispatching
        ret = obj
        if isinstance(obj, Stream) and not recast_stream:
            pass
        elif isinstance(obj, Stream) and recast_stream:
            ret = HTML(obj, encoding='utf-8')
        elif isinstance(obj, basestring):
            ret = HTML(obj, encoding='utf-8')
        elif isinstance(obj, list):
            ret = HTML(" ".join(map(str, obj)), encoding='utf-8')
        else:
            raise EnactException("Could not correctly coerce into HTML obj - " + str(obj))
        return ret


class Actions(object):
    """
    Actions is a collection common transformation functions used
    in generating HTML content.

    Enact can accept any function as a transforming function,
    and these functions can cerntainly be used as a guide for
    extending the system to fit your specific need.
    """

    transformer = Transformer()
    sanitizer = HTMLSanitizer()
    
    @staticmethod
    def setAttrs(selection, attr_dict):
        return reduce(lambda old,(attr_key, value): old | Actions.transformer.attr(attr_key, value).end(),
                        attr_dict.items(), selection)

    @staticmethod
    def removeAttrs(selection, attr_list):
        if isinstance(attr_list, basestring):
            attr_list = [attr_list]
        return Actions.setAttrs(selection, dict(zip(attr_list, itertools.repeat(None))))

    @staticmethod
    def appendAttrs(selection, attr_dict):
        def appendAttrAux(name, event):
            name = str(name)
            attrs = dict([(str(attr),value) for attr,value in event[1][1]])
            ret = attrs[name] + " " + attr_dict[name]
            return ret
        return reduce(lambda old,(attr_key, value): old | Actions.transformer.attr(attr_key, appendAttrAux).end(),
                        attr_dict.items(), selection)

    @staticmethod
    def removeFromAttrs(selection, attr_dict):
        def removeAttrAux(name, event):
            name = str(name)
            attrs = dict([(str(attr),value) for attr,value in event[1][1]])
            ret = reduce(lambda old, new: old.replace(new, ""), attr_dict[name].split(), attrs[name])
            return ret.strip()
        return reduce(lambda old,(attr_key, value): old | Actions.transformer.attr(attr_key, removeAttrAux).end(),
                        attr_dict.items(), selection)

    @staticmethod
    def content(selection, content_str):
        return selection | Actions.transformer.empty().prepend(content_str).end()

    @staticmethod
    def htmlContent(selection, html_str_or_obj):
        return Actions.content(selection, Enact.ensureHTML(html_str_or_obj))

    @staticmethod
    def contentForEach(selection, func_data_tuple):
        transformation_func = func_data_tuple[0]
        data_list = func_data_tuple[1]
        new_content = ""
        if len(func_data_tuple) > 2:
            new_content = transformation_func(data_list, *func_data_tuple[2:])
        else:
            new_content = transformation_func(data_list)
        return Actions.content(selection, new_conent)

    @staticmethod
    def append(selection, content_str):
        return selection | Actions.transformer.append(content_str).end()

    @staticmethod
    def appendHtml(selection, html_str_or_obj):
        return Actions.append(selection, Enact.ensureHTML(html_str_or_obj)).end()

    @staticmethod
    def prepend(selection, content_str):
        return selection | Actions.transformer.prepend(content_str).end()

    @staticmethod
    def prependHtml(selection, html_str_or_obj):
        return Actions.prepend(selection, Enact.ensureHTML(html_str_or_obj)).end()

    @staticmethod
    def before(selection, html_str_or_obj):
        return selection | Actions.transformer.before(Enact.ensureHTML(html_str_or_obj)).end()

    @staticmethod
    def after(selection, html_str_or_obj):
        return selection | Actions.transformer.after(Enact.ensureHTML(html_str_or_obj)).end()

    @staticmethod
    def replace(selection, html_str_or_obj):
        return selection | Actions.transformer.replace(Enact.ensureHTML(html_str_or_obj)).end()

    @staticmethod
    def remove(selection, ignored_arg):
        return selection | Actions.transformer.remove().end()

    @staticmethod
    def unwrap(selection, tag_list=None):
        if not tag_list:
            return selection | Actions.transformer.unwrap().end()
        if isinstance(tag_list, basestring):
            tag_list = [tag_list]
        #TODO We need to write a selective unwrap

    @staticmethod
    def wrap(selection, tag_list):
        if isinstance(tag_list, basestring):
            tag_list = [tag_list]
        return reduce(lambda old,tag: old | Actions.transformer.wrap(tag),
                        tag_list, selection) | Actions.transformer.end()

    @staticmethod
    def rawTransform(selection, transformer_chain):
        # Caution: there is no .end() call, you'll have to supply it yourself in the chain
        return selection | transformer_chain

    @staticmethod
    def cssSelect(selection, css_selector):
        return selection | Actions.transformer.select(Enact.cssToXpath(css_selector))

    @staticmethod
    def sanitize(selection, ignored_arg):
        return selection | Actions.sanitizer

#s = '''<div id="tutor-details" class="well span8"><p>This is a bunch of text</p><a href="http://www.tutorspree.com">Home</a></div>'''
#ss = '''<!DOCTYPE html>\n<div id="new-id" class="well span8"><p><h1>Best Tutor 2012</h1></p><p>This is a new piece of text</p><a href="http://www.tutorspree.com">Home</a></div>'''
#dd = Enact.string(s,
#             "#tutor-details", [Actions.setAttrs, {"id": "new-id"}],
#              "p", [Actions.htmlContent, "<h1>Best Tutor 2012</h1>",
#                    Actions.after, "<p>This is a new piece of text</p>",
#                    #Actions.wrap, "h5",
#                    #Actions.sanitize, None,
#                    ])
#print dd
#print ss
#print dd == ss
#s = '<div class="package" data-package-id="1"><div class="student"><div class="name">Name</div></div></div>'
#ss = '<!DOCTYPE html>\n<div class="package" data-package-id="2"><div class="student"><div class="name">lala</div></div></div>'
#dd = Enact.string(s,
#                ".package", [Actions.setAttrs, {"data-package-id": "2"}],
#                ".student .name", [Actions.content, "lala"])
#print dd == ss
#s = '<div class="package" data-package-id="1"><div class="student"><p class="name">Name</p></div></div>'
#ss = '<!DOCTYPE html>\n<div class="package" data-package-id="2"><div class="student"><p class="name">lala</p></div></div>'
#dd = Enact.string(s,
#                ".package", [Actions.setAttrs, {"data-package-id": "2"}],
#                ".student .name", [Actions.content, "lala"])
#print dd == ss
#s = '<div class="package" data-package-id="1"><div class="student"><p class="name">Name</p></div></div>'
#ss = '<div class="package" data-package-id="2"><div class="student"><p class="name">lala</p></div></div>'
#dd = Enact.string(s,
#                ".package", [Actions.setAttrs, {"data-package-id": "2"}],
#                ".student .name", [Actions.content, "lala"],
#                doctype=None)
#print dd == ss

