#!/usr/bin/env python
from optparse import OptionParser
import os
import sys
from Bio import SeqIO, motifs
from Bio.SeqRecord import SeqRecord
from Bio.Seq import Seq
from Bio.Alphabet import IUPAC
from multiprocessing import Pool
from random import gauss, sample
from numpy import load,inf, sign, dot, diag, array, cumsum, sort, sum, searchsorted, newaxis, arange, sqrt, log2, log, power, ceil, prod, zeros, concatenate
from numpy.random import rand
from itertools import repeat, chain, izip
from pygr import seqdb
from bisect import bisect_left

"""
Equation 14 from the Bailey and Elkan paper. Calculates P(X|theta_motif). That is,
the probability of the sequence given the motif model. It is defined as the product
of the frequencies of the letter at each position.

This is a modified version that uses the indicator matrix instead. Saves the trouble
of calculating the indicator matrix at each step.

Input:
I, A boolean matrix. A representation of the sequence. Has dimension Wx4, the same as the PWM
theta_motif, PWM. Columns in order of A, C, G, T. Each row must sum to 1. Number of rows must be same as X length

Output:
p, A double. P(X|theta_motif) 
"""
def pI_motif(I, theta_motif):
    ps = theta_motif[I]#some fancy indexing tricks. Gets me an array of the relevant frequencies
    p = ps.prod()
    return p

"""
Equation 15 from the Bailey and Elkan paper. Calculates P(X|theta_background). That is,
the probability of the sequence given the background model. It is defined as the product
of the frequencies the letter at each position.

This is a modified version that uses the indicator matrix instead. Saves the trouble
of calculating the indicator matrix at each step. Note also that theta_background
has been switched to theta_background_matrix, essentially a PWM for the background.

Input:
I, A boolean matrix. A representation of the sequence. Has dimension Wx4, the same as the PWM
theta_background_matrix, Matrix of probabilities for each nucleotide, in order of A, C, G, T. 
Each row must sum to 1. This is basically like the usual array, but the row vector is repeated W times

Output:
p, A double. P(X|theta_background) 
"""
def pI_background(I, theta_background_matrix):
    ps = theta_background_matrix[I]#some fancy indexing tricks. Gets me an array of the relevant frequencies
    p = ps.prod()
    return p


"""
Equation 10 from the Bailey and Elkan paper. The expectation of the Z value for the sequence X,
given the motif frequency and the motif and background models. Note that g=2, where group 1
is the motif, and group 2 is the background. We can get the expectation of the Z value of 
the background by taking 1 - Z0.


This is a modified version that uses the indicator matrix instead. Saves the trouble
of calculating the indicator matrix at each step. 

Input:
I, indicator matrix. Represents a sequence.
theta_motif, a matrix. The PWM of the motif.
theta_background_matrix, a matrix. Essentially a PWM of the background model.
lambda_motif, a double. The fraction of motifs among the sequences.

Output:
Z0 - Expected value of Z for the the indicator matrix I
"""
def Z0_I(I,theta_motif, theta_background_matrix,lambda_motif):
    a = pI_motif(I,theta_motif)*lambda_motif#saves a calculation
    b = pI_background(I,theta_background_matrix)*(1-lambda_motif)#saves another calculation
    Z0 = a/(a + b)
    return Z0

"""
Function that accepts a string, X, and returns an indicator matrix, I. Representing
each sequence as an indicator matrix will save time and memory.

Input:
X, a string. The sequence to be converted to an indicator matrix

Output:
I, a boolean matrix. The indicator matrix. Has dimensions Wx4. Each row is a position along the string.
Each column represents a nucleotide, in alphabetical order.
"""
def sequenceToI(X):
    l = array(list(X))#convert the string to an array of characters
    d = array(['A','C','G','T'])#the 4 nucleotides
    I = l[:,newaxis] == d#construct the matrix
    return I

"""
The E-step of the EM algorithm. Accepts the list of indicator matrices I, the current motif
frequency lambda_motif, and both PWMs. Returns the expected Z values, and the 
expected number of times each letter appears c_jk.

Note that this uses the indicator matrices only. 

Input:
I, a list of indicator matrices. This might get confusing with I being a list here and a matrix elsewhere.
theta_motif, a matrix. The PWM of the motif.
theta_background_matrix, a matrix. Essentially a PWM of the background model.
lambda_motif, a double. The fraction of motifs among the sequences.

Output:
Z, a list of double. Same dimensions as I. Expected value of subsequence generated by motif
c0, an array. Equation 16. Expected number of times each letter appears generate by background
c, a matrix. Dimension Wx4. Equation 17. Expected number of times each letter appears at
each position generated by motif model.

"""
def E(I, theta_motif, theta_background_matrix, lambda_motif):
    Z = [[Z0_I(Iij,theta_motif, theta_background_matrix,lambda_motif) for Iij in Ii] for Ii in I]
    L = theta_motif.shape[1]#Alphabet size same as number of columns in PWM
    c0 = zeros(L)
    c = zeros(theta_motif.shape)
    for Zi, Ii in izip(Z,I):
        for Zij, Iij in izip(Zi, Ii):
            c0 = c0 + (1 - Zij)*Iij.sum(axis=0)
            c = c + Zij*Iij#notice how this leaves the possibility of introducing erasing factors
    return Z, c0, c

"""
The M-step of the EM algorithm. Accepts the expected Z values of each sequence and the expected
number of times each letter appears in each position (c_jk matrix), and returns the updated
motif frequency and PWM.

Input: 
Z, a list with the same dimensions as the subsequences list
n, the number of subsequences
c0, an array. Equation 16. Expected number of times each letter appears generate by background
c, a matrix. Dimension Wx4. Equation 17. Expected number of times each letter appears at
each position generated by motif model.

Output:
lambda_motif, a double. Motif frequency 
theta_motif, a matrix. PWM of the motif
theta_background_matrix, a matrix. Essentially a PWM of the background model
"""
def M(Z, n, c0, c):
    Z_total = 0
    for Zi in Z:
        for Zij in Zi:
            Z_total = Z_total + Zij
    lambda_motif = Z_total/n
    c0 = array([c0])
    c = concatenate((c0,c))
    f = dot(diag(1/c.sum(axis=1)),c)
    theta_motif = f[1:]
    theta_background = array([f[0]])
    theta_background_matrix = theta_background.repeat(theta_motif.shape[0],axis=0)
    return lambda_motif, theta_motif, theta_background_matrix

"""
Absolute Euclidean distance between two arrays, u and v. This function
is for the EM algorithm's convergence.

Input:
u and v, arrays.

Output:
Euclidean distance between u and v.
"""
def dist(u,v):
    w = u - v
    w = power(w,2)
    return sqrt(w.sum())

"""
The EM algorithm. 

Input:
Y, pygr database. dataset of sequences (As of 6/28/13, assume each sequence contains 1 subsequence
theta_motif, motif PWM matrix guess
theta_background_matrix, background PWM matrix guess
lambda_motif, motif frequency guess

Output:
theta_motif, motif PWM matrix
theta_background_matrix, background PWM matrix
lambda_motif, motif frequency
"""
def Online_EM(Y, theta_motif, theta_background_matrix, lambda_motif):
    W = theta_motif.shape[0]#get the length of the motif
    s1_1 = lambda_motif#the expected number of occurrences of the motif
    s1_2 = theta_motif#the matrix holding the expected number of times a letter appears in each position, motif
    s2_2 = theta_background_matrix#the matrix holding the expected number of times a letter appears in each position, background
    n = 1#the counter
    for y in Y:#iterate through each sequence in the FASTA file
        I = sequenceToI(str(y))#convert the FASTA sequence to a string and then an indicator matrix
        step = 0.85#the online step size. May need to change this
        #E-step
        ds1_1 = Z0_I(I,theta_motif, theta_background_matrix,lambda_motif)
        ds1_2 = ds1_1*I
        ds2_2 = (1-ds1_1)*I
        s1_1 = s1_1 + step*(ds1_1 - s1_1)
        s1_2 = s1_2 + step*(ds1_2 - s1_2)
        s2_2 = s2_2 + step*(ds2_2 - s2_2)
        #M-step
        lambda_motif = s1_1
        theta_motif = s1_2
        theta_background = s2_2.sum(axis = 0)#collapse the expected background counts into a single array
        theta_background = theta_background/theta_background.sum()#divide by the total counts to normalize to 1
        theta_background = array([theta_background])#prepare background for repeat
        theta_background_matrix = theta_background.repeat(W,axis=0)
        #update the counter
        n = n + 1
    return theta_motif, theta_background_matrix, lambda_motif
    #E-step, this may be superfluous
    #Z, c0, c = E(I, theta_motif, theta_background_matrix, lambda_motif)
    #M-step, this may be superfluous
    #lambda_motif, theta_motif, theta_background_matrix = M(Z, n, c0, c)
    """
    for k in xrange(MAXITER):
        theta_motif_old = theta_motif#this is the only thing I need to save
        #E-step
        Z, c0, c = E(I, theta_motif, theta_background_matrix, lambda_motif)
        #M-step
        lambda_motif, theta_motif, theta_background_matrix = M(Z, n, c0, c)
        if dist(theta_motif, theta_motif_old) < TOL:
            break
    return lambda_motif, theta_motif, theta_background_matrix, k
    """

"""
The main online MEME algorithm.

Input:
Y, pygr database. dataset of sequences
W, width of motifs to search for
NPASSES, number of distinct motifs to search for

Assume that each sequence is the size of the motif for now.
That is, Y = X.
"""
def meme(Y,W,NPASSES):
    #6/28/13, check with initial conditions matching solution
    lambda_motif = 0.5
    theta_motif = load('NRF1_Motif.npy')
    theta_uniform_background = array([[0.25, 0.25, 0.25, 0.25]])
    theta_uniform_background_matrix = theta_uniform_background.repeat(W,axis=0)#the initial guess for background is uniform distribution
    theta_motif, theta_background_matrix, lambda_motif = Online_EM(Y, theta_motif, theta_uniform_background_matrix, lambda_motif)
    outputMotif(lambda_motif, theta_motif, theta_background_matrix)
    
"""
Outputs the motif as a web logo.

Input:
lambda_motif - a double, fraction of subsequences 
theta_motif - a numpy array, the PWM
theta_background_matrix - a numpy array, the background model
"""
def outputMotif(lambda_motif, theta_motif, theta_background_matrix):
    c = theta_motif.T
    d = {'A':c[0],'C':c[1],'G':c[2],'T':c[3]}
    m = motifs.Motif(alphabet=IUPAC.unambiguous_dna,counts=d)
    b = theta_background_matrix[0]
    back = {'A':b[0],'C':b[1],'G':b[2],'T':b[3]}
    m.background = back
    m.weblogo('results.png')
    #for now, just print, but will have to output a png later
    print lambda_motif
    print theta_motif
    print theta_background_matrix

if __name__ == "__main__":
    usage = "usage: %prog [options] <input FASTA>"
    description = "The program applies the Online MEME algorithm to find motifs in a FASTA file"
    parser = OptionParser(usage=usage,description=description)
    parser.add_option("-p", "--processes", help="optional number of parallelized processes")
    parser.add_option("-w", "--width", help="File holding motif(s). Default: no motifs", default="10")
    parser.add_option("-n", "--nummotifs", help="Number of sequences to write. Default:100", default="1")
    (options, args) = parser.parse_args()
    w = int(options.width)
    nmotifs = int(options.nummotifs)
    if len(args) == 1:#the program is correctly used, so do MEME
        sp = seqdb.SequenceFileDB(args[0])
        meme(sp,w,nmotifs)
        sp.close()
    else:
        parser.print_help()