#!/usr/bin/python
#
# Copyright (c) 2014-2015 Sylvain Peyrefitte
#
# This file is part of rdpy.
#
# rdpy is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program. If not, see <http://www.gnu.org/licenses/>.
#

import argparse
import warnings
def warn(*args, **kwargs):
    pass
warnings.warn = warn

import sys
import ipaddress
from PyQt4 import QtCore, QtGui
from rdpy.protocol.rdp import rdp
from rdpy.ui.qt4 import RDPBitmapToQtImage
import rdpy.core.log as log
from rdpy.core.error import RDPSecurityNegoFail
from twisted.internet import task
import json
# set log level
log._LOG_LEVEL = log.Level.INFO

def create_template_struct(target):
    result = {'data':
                  {'rdp':
                       {'status': 'success',
                        'result':
                            {'response':
                                 {'request': {}
                                  }
                             }
                        }
                   }
              }
    return result

def create_template_error(target,
                          error_str):
    _tmp = {"ip": target["ip"],
            "port": target["port"],
            "data": {}}
    _tmp["data"]['rdp'] = {'status': 'unknown-error',
                           'error': error_str}
    return _tmp


def check_ip(ipstr):
    try:
        ipaddress.ip_address(ipstr.decode())
        return True
    except:
        pass


def make_document_from_response(_buffer,
                                target):


    def update_line(json_record,
                    target):

        json_record["ip"] = target["ip"]
        json_record["port"] = int(target["port"])
        return json_record

    _default_record = create_template_struct(target)
    _default_record['data']['rdp']['status'] = "success"
    data_base64 = QtCore.QByteArray()
    buf = QtCore.QBuffer(data_base64)
    _buffer.save(buf, 'JPG')
    string_base64 = str(data_base64.toBase64())
    _default_record['data']['rdp']['result']['response']['image'] = string_base64
    _default_record['data']['rdp']['result']['response']['size'] = data_base64.size()
    _default_record['data']['rdp']['result']['response']['request']['width'] = target['width']
    _default_record['data']['rdp']['result']['response']['request']['height'] = target['height']
    _default_record['data']['rdp']['result']['response']['request']['timeout'] = target['timeout']
    return update_line(_default_record, target)


class RDPScreenShotFactory(rdp.ClientFactory):
    """
    @summary: Factory for screenshot exemple
    """
    __INSTANCE__ = 0
    __STATE__ = []

    def __init__(self, reactor, app, target):
        """
        @param reactor: twisted reactor
        @param width: {integer} width of screen
        @param height: {integer} height of screen
        @param path: {str} path of output screenshot
        @param timeout: {float} close connection after timeout s without any updating
        """
        RDPScreenShotFactory.__INSTANCE__ += 1
        self._reactor = reactor
        self._app = app
        self._width = target["width"]
        self._height = target["height"]
        # self._path = path
        self._path = ""
        self._timeout = target["timeout"]
        #NLA server can't be screenshooting
        self._security = rdp.SecurityLevel.RDP_LEVEL_SSL

    def clientConnectionLost(self, connector, reason):
        """
        @summary: Connection lost event
        @param connector: twisted connector use for rdp connection (use reconnect to restart connection)
        @param reason: str use to advertise reason of lost connection
        """

        if reason.type == RDPSecurityNegoFail and self._security != "rdp":
            # log.info("due to RDPSecurityNegoFail try standard security layer")
            self._security = rdp.SecurityLevel.RDP_LEVEL_RDP
            connector.connect()
            return
        #
        # # log.info("connection lost : %s" % reason)
        RDPScreenShotFactory.__STATE__.append((connector.host, connector.port, reason))
        RDPScreenShotFactory.__INSTANCE__ -= 1
        if(RDPScreenShotFactory.__INSTANCE__ == 0):
            self._reactor.stop()
            self._app.exit()

    def clientConnectionFailed(self, connector, reason):
        """
        @summary: Connection failed event
        @param connector: twisted connector use for rdp connection (use reconnect to restart connection)
        @param reason: str use to advertise reason of lost connection
        """
        # log.info("connection failed : %s"%reason)
        RDPScreenShotFactory.__STATE__.append((connector.host, connector.port, reason))
        RDPScreenShotFactory.__INSTANCE__ -= 1
        if(RDPScreenShotFactory.__INSTANCE__ == 0):
            self._reactor.stop()
            self._app.exit()

    def buildObserver(self, controller, addr):
        """
        @summary: build ScreenShot observer
        @param controller: RDPClientController
        @param addr: address of target
        """
        class ScreenShotObserver(rdp.RDPClientObserver):
            """
            @summary: observer that connect, cache every image received and save at deconnection
            """
            def __init__(self, controller, width, height, path, timeout, reactor):
                """
                @param controller: {RDPClientController}
                @param width: {integer} width of screen
                @param height: {integer} height of screen
                @param path: {str} path of output screenshot
                @param timeout: {float} close connection after timeout s without any updating
                @param reactor: twisted reactor
                """
                rdp.RDPClientObserver.__init__(self, controller)
                self._buffer = QtGui.QImage(width, height, QtGui.QImage.Format_RGB32)
                self._path = path
                self._timeout = timeout
                self._startTimeout = False
                self._reactor = reactor
                self._need_save = False

            def onUpdate(self, destLeft, destTop, destRight, destBottom, width, height, bitsPerPixel, isCompress, data):
                """
                @summary: callback use when bitmap is received 
                """
                if data:
                    self._need_save = True
                image = RDPBitmapToQtImage(width, height, bitsPerPixel, isCompress, data)

                with QtGui.QPainter(self._buffer) as qp:
                # draw image
                    qp.drawImage(destLeft, destTop, image, 0, 0, destRight - destLeft + 1, destBottom - destTop + 1)
                if not self._startTimeout:
                    self._startTimeout = False
                    self._reactor.callLater(self._timeout, self.checkUpdate)

            def onReady(self):
                """
                @summary: callback use when RDP stack is connected (just before received bitmap)
                """
                # log.info("connected %s" % addr)

            def onSessionReady(self):
                """
                @summary: Windows session is ready
                @see: rdp.RDPClientObserver.onSessionReady
                """
                pass

            def onClose(self):
                """
                @summary: callback use when RDP stack is closed
                """
                if self._need_save:
                    result_json = make_document_from_response(self._buffer, target)
                    print json.dumps(result_json)
                else:
                    result_json = create_template_error(target,
                                                        'some errors')
                    print json.dumps(result_json)

            def checkUpdate(self):
                self._controller.close()

        controller.setScreen(self._width, self._height)
        controller.setSecurityLevel(self._security)
        return ScreenShotObserver(controller, self._width, self._height, self._path, self._timeout, self._reactor)


def main_run(target):
    """
    @summary: main algorithm
    @param height: {integer} height of screenshot
    @param width: {integer} width of screenshot
    @param timeout: {float} in sec
    @param hosts: {list(str(ip[:port]))}
    @return: {list(tuple(ip, port, Failure instance)} list of connection state
    """
    #create application
    app = QtGui.QApplication(sys.argv)

    #add qt4 reactor
    import qt4reactor
    qt4reactor.install()

    from twisted.internet import reactor

    reactor.connectTCP(target["ip"], target["port"],
                       RDPScreenShotFactory(reactor, app, target))

    reactor.runReturn()


    app.exec_()
    return RDPScreenShotFactory.__STATE__


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description='Screenshot RDP')
    parser.add_argument(
        "--mode",
        dest='mode',
        type=str,
        default='stdout',
        help="save to file or print to stdout(json), default: stdout")

    parser.add_argument(
        "--output-dir",
        dest='output_dir',
        type=str,
        default='/tmp/',
        help="save to file in directory, defalut: /tmp/")


    parser.add_argument(
        "--target",
        dest='target',
        type=str,
        help="width")

    parser.add_argument(
        "--width",
        dest='width',
        type=int,
        default=800,
        help="width")

    parser.add_argument(
        "--height",
        dest='height',
        type=int,
        default=600,
        help="height")

    parser.add_argument(
        "--timeout",
        dest='timeout',
        type=int,
        default=5,
        help="timeout")

    args = parser.parse_args()
    target = {}
    if not args.target:
        print "not found --target ip, ip:port"
        parser.print_help()
        exit(1)
    else:
        target_port = 3389
        if ":" in args.target:
            target_ip, target_port = (args.target).split(":")
            if check_ip(target_ip) and target_port.isdigit():
                target["ip"] = target_ip
                target["port"] = int(target_port)
        else:
            if check_ip(args.target):
                target["ip"] = args.target
                target["port"] = target_port
    if not target:
        print "error with %s --target ip, ip:port"%(args.target)
        parser.print_help()
        exit(1)
    target['height'] = args.height
    target['width'] = args.width
    target['timeout'] = args.timeout
    target['mode'] = args.mode
    main_run(target)

