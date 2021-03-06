############################################################
#                                                          #
#                          hprose                          #
#                                                          #
# Official WebSite: http://www.hprose.com/                 #
#                   http://www.hprose.net/                 #
#                   http://www.hprose.org/                 #
#                                                          #
############################################################

############################################################
#                                                          #
# hprose/client.py                                         #
#                                                          #
# hprose client for python 3.0+                            #
#                                                          #
# LastModified: Dec 1, 2012                                #
# Author: Ma Bingyao <andot@hprfc.com>                     #
#                                                          #
############################################################

import threading, types
from sys import modules
from hprose.io import *
from hprose.common import *

class _Method(object):
    def __init__(self, invoke, name):
        self.__invoke = invoke
        self.__name = name
    def __getattr__(self, name):
        return _Method(self.__invoke, self.__name + '_' + name)
    def __call__(self, *args, **kargs):
        callback = kargs.get('callback', None)
        onerror = kargs.get('onerror', None)
        byRef = kargs.get('byRef', False)
        resultMode = kargs.get('resultMode', HproseResultMode.Normal)
        return self.__invoke(self.__name, list(args), callback, onerror, byRef, resultMode)

class _Proxy(object):
    def __init__(self, invoke):
        self.__invoke = invoke
    def __getattr__(self, name):
        return _Method(self.__invoke, name)

class _AsyncInvoke(object):
    def __init__(self, invoke, name, args, callback, onerror, byRef, resultMode):
        self.__invoke = invoke
        self.__name = name
        self.__args = args
        self.__callback = callback
        self.__onerror = onerror
        self.__byRef = byRef
        self.__resultMode = resultMode
    def __call__(self):
        try:
            result = self.__invoke(self.__name, self.__args, self.__byRef, self.__resultMode)
            argcount = self.__callback.func_code.co_argcount
            if argcount == 0:
                self.__callback()
            elif argcount == 1:
                self.__callback(result)
            else:
                self.__callback(result, self.__args)    
        except Exception as e:
            if self.__onerror != None:
                self.__onerror(self.__name, e)

class HproseClient(object):
    def __init__(self, uri = None):
        self.onError = None
        self._filter = HproseFilter()
        self.useService(uri)

    def __getattr__(self, name):
        return _Method(self.invoke, name)

    def invoke(self, name, args = (), callback = None, onerror = None, byRef = False, resultMode = HproseResultMode.Normal):
        if callback == None:
            return self.__invoke(name, args, byRef, resultMode)
        else:
            if isinstance(callback, str):
                callback = getattr(modules['__main__'], callback, None)
            if not hasattr(callback, '__call__'):
                raise HproseException("callback must be callable")
            if onerror == None:
                onerror = self.onError
            if onerror != None:
                if isinstance(onerror, str):
                    onerror = getattr(modules['__main__'], onerror, None)
                if not hasattr(onerror, '__call__'):
                    raise HproseException("onerror must be callable")
            threading.Thread(target = _AsyncInvoke(self.__invoke, name, args,
                                                   callback, onerror,
                                                   byRef, resultMode)).start()

    def useService(self, uri = None):
        if uri != None:
            self.setUri(uri)
        return _Proxy(self.invoke)
        
    def setUri(self, uri):
        raise NotImplementedError

    uri = property(fset = setUri)

    def getFilter(self):
        return self._filter

    def setFilter(self, filter):
        self._filter = filter

    def _getInovkeContext(self):
        raise NotImplementedError
    
    def _getOutputStream(self, context):
        raise NotImplementedError

    def _sendData(self, context):
        raise NotImplementedError

    def _getInputStream(self, context):
        raise NotImplementedError

    def _endInvoke(self, context):
        raise NotImplementedError

    def __invoke(self, name, args, byRef, resultMode):
        context = self._getInovkeContext()
        stream = self._getOutputStream(context)
        stream.write(HproseTags.TagCall)
        hproseWriter = HproseWriter(stream)
        hproseWriter.writeString(name, False)
        if (len(args) > 0) or byRef:
            hproseWriter.reset()
            hproseWriter.writeList(args, False)
            if byRef:
                hproseWriter.writeBoolean(True)
        hproseWriter.stream.write(HproseTags.TagEnd)
        result = None
        error = None
        try:
            self._sendData(context)
            stream = self._getInputStream(context)
            if resultMode == HproseResultMode.RawWithEndTag:
                result = stream.readall()
                return result
            if resultMode == HproseResultMode.Raw:
                result = stream.readall()[:-1]
                return result
            hproseReader = HproseReader(stream)
            while True:
                tag = hproseReader.checkTags((HproseTags.TagResult,
                                              HproseTags.TagArgument,
                                              HproseTags.TagError,
                                              HproseTags.TagEnd))
                if tag == HproseTags.TagEnd: break
                if tag == HproseTags.TagResult:
                    if resultMode == HproseResultMode.Serialized:
                        s = hproseReader.readRaw()
                        result = s.getvalue()
                        s.close()
                    else:
                        hproseReader.reset()
                        result = hproseReader.unserialize()
                if tag == HproseTags.TagArgument:
                    hproseReader.reset()
                    a = hproseReader.readList()
                    if isinstance(args, list):
                        for i in range(len(args)):
                            args[i] = a[i]
                if tag == HproseTags.TagError:
                    hproseReader.reset()
                    error = hproseReader.readString()
        finally:
            self._endInvoke(context)
        if error != None:
            raise HproseException(error)
        return result
