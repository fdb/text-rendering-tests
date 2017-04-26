#!/usr/bin/python2.7
# -*- coding: utf-8 -*-
#
# Copyright 2016 Unicode Inc. All rights reserved.
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

from __future__ import unicode_literals
import argparse, datetime, itertools, os, re, subprocess, time
import xml.etree.ElementTree as etree
import svgutil


FONTTEST_NAMESPACE = '{https://github.com/OpenType/fonttest}'
FONTTEST_ID = FONTTEST_NAMESPACE + 'id'
FONTTEST_FONT = FONTTEST_NAMESPACE + 'font'
FONTTEST_RENDER = FONTTEST_NAMESPACE + 'render'
FONTTEST_VARIATION = FONTTEST_NAMESPACE + 'var'


class ConformanceChecker:
    def __init__(self, engine):
        self.engine = engine
        if self.engine == 'OpenType.js':
            self.command = 'src/third_party/opentypejs/opentype.js/bin/test-render'
        else:
            self.command = 'build/out/Default/fonttest'
        self.datestr = self.make_datestr()
        self.reports = {}  # filename --> HTML ElementTree
        self.conformance = {}  # testcase -> True|False
        self.observed = {}  # testcase --> SVG ElementTree

    def make_datestr(self):
        now = datetime.datetime.now()
        return '%s %d, %d' % (time.strftime("%B"), now.day, now.year)

    def check(self, testfile):
        all_ok = True
        doc = etree.parse(testfile).getroot()
        self.reports[testfile] = doc
        for e in doc.findall(".//*[@class='expected']"):
            testcase = e.attrib[FONTTEST_ID]
            font = os.path.join('fonts', e.attrib[FONTTEST_FONT])
            render = e.attrib.get(FONTTEST_RENDER)
            variation = e.attrib.get(FONTTEST_VARIATION)
            expected_svg = e.find('svg')
            self.normalize_svg(expected_svg)
            command = [self.command, '--font=' + font,
                       '--testcase=' + testcase, '--engine=' + self.engine]
            if render: command.append('--render=' + render)
            if variation: command.append('--variation=' + variation)
            try:
                observed = subprocess.check_output(command)
            except subprocess.CalledProcessError:
                observed = '<error/>'
            observed = re.sub(r'>\s+<', '><', observed)
            observed = observed.replace(
                'xmlns="http://www.w3.org/2000/svg"', '')
            observed_svg = etree.fromstring(observed)
            self.normalize_svg(observed_svg)
            self.observed[testcase] = observed_svg
            ok = svgutil.is_similar(expected_svg, observed_svg, maxDelta=1.0)
            all_ok = all_ok and ok
            self.conformance[testcase] = ok
            groups = testcase.split('/')
            for i in range(len(groups)):
                group = '/'.join(groups[:i])
                self.conformance[group] = (ok and
                                           self.conformance.get(group, True))
        print "%s %s" % ("PASS" if all_ok else "FAIL", testfile)

    def normalize_svg(self, svg):
        strip_path = lambda p: re.sub(r'\s+', ' ', p).strip()
        for path in svg.findall('.//path[@d]'):
            path.attrib['d'] = strip_path(path.attrib['d'])

    def write_report(self, path):
        report = etree.parse('testcases/index.html').getroot()
        report.find("./body/h2").text = self.datestr + ' · ' + self.engine
        summary = report.find("./body//*[@id='SummaryText']")
        fails = [k for k, v in self.conformance.items() if k and not v]
        fails = sorted(set([t.split('/')[0] for t in fails]))
        if len(fails) == 0:
            summary.text = 'All tests have passed.'
        else:
            summary.text = 'Some tests have failed. See '
            for f in fails:
                if f is not fails[0]:
                    if f is fails[-1]:
                        etree.SubElement(summary, None).text = ', and '
                    else:
                        etree.SubElement(summary, None).text = ', '
                link = etree.SubElement(summary, 'a')
                link.text, link.attrib['href'] = f, '#' + f
            etree.SubElement(summary, None).text = ' for details.'

        head = report.find("./head")
        for sheet in list(head.findall("./link[@rel='stylesheet']")):
            href = sheet.attrib.get('href')
            if href and '://' not in href:
                internalStyle = etree.SubElement(head, 'style')
                with open(os.path.join('testcases', href), 'r') as sheetfile:
                    internalStyle.text = sheetfile.read().decode('utf-8')
                head.remove(sheet)

        for filename, doc in sorted(self.reports.items()):
            for e in doc.findall(".//*[@class='observed']"):
                e.append(self.observed.get(e.attrib[FONTTEST_ID]))
            for e in doc.findall(".//*[@class='conformance']"):
                if self.conformance.get(e.attrib[FONTTEST_ID]):
                    e.text, e.attrib['class'] = '✓', 'conformance-pass'
                else:
                    e.text, e.attrib['class'] = '✖', 'conformance-fail'

            for subElement in doc.find('body'):
                report.find('body').append(subElement)

        with open(path, 'w') as outfile:
            xml = etree.tostring(report, encoding='utf-8')
            xml = xml.replace(b'svg:', b'')  # work around browser bugs
            outfile.write(xml)


def build(engine):
    if engine == 'OpenType.js':
        subprocess.check_call(['npm', 'install'], cwd='./src/third_party/opentypejs/opentype.js')
    else:
        subprocess.check_call(
            './src/third_party/gyp/gyp -f make --depth . '
            '--generator-output build  src/fonttest/fonttest.gyp'.split())
        subprocess.check_call(['make', '-s', '--directory', 'build'])


def main():
    etree.register_namespace('svg', 'http://www.w3.org/2000/svg')
    etree.register_namespace('xlink', 'http://www.w3.org/1999/xlink')
    parser = argparse.ArgumentParser()
    parser.add_argument('--engine',
                        choices=['FreeStack', 'CoreText', 'DirectWrite', 'OpenType.js'],
                        default='FreeStack')
    parser.add_argument('--output', help='path to report file being written')
    args = parser.parse_args()
    build(engine=args.engine)
    checker = ConformanceChecker(engine=args.engine)
    for filename in os.listdir('testcases'):
        if (filename == 'index.html'
                or not filename.endswith('.html')):
            continue
        checker.check(os.path.join('testcases', filename))
    print('PASS' if checker.conformance.get('') else 'FAIL')
    if args.output:
        checker.write_report(args.output)


if __name__ == '__main__':
    main()
