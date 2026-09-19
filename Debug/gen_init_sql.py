# -*- coding: utf-8 -*-
import sys, os

DD = chr(36) * 2
SQ = chr(39)
DQ = chr(34)
NL = chr(10)

root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
out = os.path.join(root, chr(87)+chr(101)+chr(98)+chr(65)+chr(80)+chr(73), chr(105)+chr(110)+chr(105)+chr(116)+chr(46)+chr(115)+chr(113)+chr(108))

def w(f, line=chr(0)):
    if line == chr(0):
        f.write(NL)
    else:
        f.write(line + NL)

def build(path):
    with open(path, chr(119), encoding=chr(117)+chr(116)+chr(102)+chr(45)+chr(56)) as f:
        w(f, chr(45)+chr(45)+chr(32)+chr(61)*76)
        w(f, chr(45)+chr(45)+chr(32)+chr(99)+chr(104)+chr(97)+chr(110)+chr(45)+chr(115)+chr(116)+chr(111)+chr(99)+chr(107)+chr(45)+chr(109)+chr(97)+chr(110)+chr(97)+chr(103)+chr(101)+chr(58)+chr(32)+chr(80)+chr(111)+chr(115)+chr(116)+chr(103)+chr(114)+chr(101)+chr(83)+chr(81)+chr(76)+chr(32)+chr(105)+chr(110)+chr(105)+chr(116)+chr(32)+chr(115)+chr(99)+chr(114)+chr(105)+chr(112)+chr(116))
        w(f, chr(45)+chr(45)+chr(32)+chr(61)*76)
        w(f)
        w(f, chr(67)+chr(82)+chr(69)+chr(65)+chr(84)+chr(69)+chr(32)+chr(79)+chr(82)+chr(32)+chr(82)+chr(69)+chr(80)+chr(76)+chr(65)+chr(67)+chr(69)+chr(32)+chr(70)+chr(85)+chr(78)+chr(67)+chr(84)+chr(73)+chr(79)+chr(78)+chr(32)+chr(117)+chr(112)+chr(100)+chr(97)+chr(116)+chr(101)+chr(95)+chr(117)+chr(112)+chr(100)+chr(97)+chr(116)+chr(101)+chr(100)+chr(95)+chr(97)+chr(116)+chr(95)+chr(99)+chr(111)+chr(108)+chr(117)+chr(109)+chr(110)+chr(40)+chr(41))
        w(f, chr(82)+chr(69)+chr(84)+chr(85)+chr(82)+chr(78)+chr(83)+chr(32)+chr(84)+chr(82)+chr(73)+chr(71)+chr(71)+chr(69)+chr(82)+chr(32)+chr(65)+chr(83)+chr(32)+DD)
        w(f, chr(66)+chr(69)+chr(71)+chr(73)+chr(78))
        w(f, chr(32)*4+chr(78)+chr(69)+chr(87)+chr(46)+chr(117)+chr(112)+chr(100)+chr(97)+chr(116)+chr(101)+chr(100)+chr(95)+chr(97)+chr(116)+chr(32)+chr(61)+chr(32)+chr(78)+chr(79)+chr(87)+chr(40)+chr(41)+chr(59))
        w(f, chr(32)*4+chr(82)+chr(69)+chr(84)+chr(85)+chr(82)+chr(78)+chr(32)+chr(78)+chr(69)+chr(87)+chr(59))
        w(f, chr(69)+chr(78)+chr(68)+chr(59))
        w(f, DD+chr(32)+chr(76)+chr(65)+chr(78)+chr(71)+chr(85)+chr(65)+chr(71)+chr(69)+chr(32)+chr(112)+chr(108)+chr(112)+chr(103)+chr(115)+chr(113)+chr(108)+chr(59))

if __name__ == chr(95)*2+chr(109)+chr(97)+chr(105)+chr(110)+chr(95)*2:
    build(out)
    print(chr(68)+chr(111)+chr(110)+chr(101)+chr(32)+chr(58)+chr(32)+out)
