import os
import numpy as np
import cuv_python as cp
from minibatch_provider import MiniBatchProviderEmpty


class MLP:
  def __init__(self, cfg, weights,biases):
    self.cfg=cfg
    self.NumCorrect = 0
    self.Errorrate=[]
    self.testError=[]
    self.NumberOfLayers = cfg.num_layers+1

    self.preEpochHook = lambda mlp,epoch: mlp

    self.Weights = weights

    self.DeltaWeightsOld = []
    self.WeightsLearnRate = []
    self.dWeights = []
    self.dBias = []

    self.Bias = biases
    self.DeltaBiasOld = []
    self.BiasLearnRate = []
    l = 0.001

    self.NumberOfNeuronsPerLayer = []
    for i in xrange(self.NumberOfLayers-2):
        #self.Weights.append(newWeights)
        dim1, dim2 = self.Weights[i].shape
        self.createCopyFilled(self.DeltaWeightsOld,self.Weights[i] , 0)
        self.createCopyFilled(self.WeightsLearnRate,self.Weights[i] , l)
        if not self.cfg.finetune_online_learning or (self.cfg.finetune_online_learning and self.cfg.finetune_rprop):
            self.createCopyFilled(self.dWeights,self.Weights[i] , 0)
            self.createCopyFilled(self.dBias,self.Bias[i] , 0)
        self.createFilled(self.DeltaBiasOld, dim2, 1, 0)
        self.createFilled(self.BiasLearnRate, dim2, 1, l)
        self.NumberOfNeuronsPerLayer.append(dim1)

    # create dense matrix for last layer
    dim1,dim2 = self.Weights[-1].shape[1], self.cfg.num_classes
    if self.cfg.load and self.loadLastLayer(dim1,dim2):
        pass
    else:
        self.Weights.append(cp.dev_tensor_float_cm([dim1,dim2]))
        cp.fill_rnd_uniform(self.Weights[-1])
        #print "Initializing weights with rnd(%2.5f)", 
        cp.apply_scalar_functor(self.Weights[-1],cp.scalar_functor.SUBTRACT, 0.5)
        #cp.apply_scalar_functor(self.Weights[-1],cp.scalar_functor.MULT, 1./math.sqrt(self.Weights[-2].w))
        cp.apply_scalar_functor(self.Weights[-1],cp.scalar_functor.MULT, 1./self.Weights[-2].shape[1])
        self.createFilled(self.Bias, dim2, 1, 0)
    self.createFilled(self.DeltaBiasOld, dim2, 1, 0)
    self.createFilled(self.BiasLearnRate, dim2, 1, l)
    self.createFilled(self.DeltaWeightsOld,dim1,dim2,0)
    self.createFilled(self.WeightsLearnRate,dim1,dim2,l)
    if not self.cfg.finetune_online_learning or (self.cfg.finetune_online_learning and self.cfg.finetune_rprop):
            self.createCopyFilled(self.dWeights,self.Weights[-1] , 0)
            self.createCopyFilled(self.dBias,self.Bias[-1] , 0)
    self.NumberOfNeuronsPerLayer.append(dim1)
    self.NumberOfNeuronsPerLayer.append(dim2)

    self.reconstruction_error = []

  def createFilled(self, matList, dim1, dim2, value):
    if dim2==1:
        matList.append(cp.dev_tensor_float([dim1]))
    else:
        matList.append(cp.dev_tensor_float_cm([dim1, dim2]))
    cp.fill(matList[-1], value)

  def createCopyFilled(self, matList, someMat, value):
      if len(someMat.shape)<2 or someMat.shape[1] == 1:
          matList.append(cp.dev_tensor_float(someMat.shape))
      else:
          matList.append(cp.dev_tensor_float_cm(someMat.shape))
      cp.fill(matList[-1], value)


  def __del__(self):
    for i in xrange(self.NumberOfLayers):
        self.Weights[i].dealloc()
        self.WeightsLearnRate[i].dealloc()
        self.Bias[i].dealloc()
        self.BiasLearnRate[i].dealloc()
        self.DeltaWeightsOld[i].dealloc()
        self.DeltaBiasOld[i].dealloc()

  def save(self, path):
      for i,w in enumerate(self.Weights):
          w.save(os.path.join(path, "weight-%d-mlp.npy"%i))
      for i,b in enumerate(self.Bias):
          b.save(os.path.join(path, "bias-%d-hi-mlp.npy"%i))

  def train(self, mbatch_provider, numberRounds, batchSize, useRPROP = 0):
    self.useRPROP = useRPROP

    for r in xrange(numberRounds):
        numberPictures = 0

        print self.cfg.workdir + ": Epoch ", r+1, "/", numberRounds
        self.preEpochHook(self, r)

        self.NumCorrect = 0
        updateOnlyLast = r < self.cfg.finetune_onlylast

        teachbatch = None

        batch_idx = 0
        output, indices = [], []
        while True:
            try:
                output= []
                output.append(cp.dev_tensor_float_cm([self.cfg.px*self.cfg.py*self.cfg.maps_bottom,batchSize]))
                teachbatch = mbatch_provider.getMiniBatch(batchSize, output[0], return_teacher=True, id=batch_idx)

                numberPictures += teachbatch.shape[1]
                batch_idx += 1

                # forward pass trough all layers
                for i in xrange(self.NumberOfLayers-1):
                   linear = self.cfg.finetune_softmax and i==self.NumberOfLayers-2 # set output layer to linear
                   output.append(self.forward(output[i], self.Weights[i], self.Bias[i], linear=linear))


                self.NumCorrect += self.getCorrect(output[-1], teachbatch)

                ## backward pass
                self.backward(output, teachbatch,indices, batchSize, updateOnlyLast, batch_idx)

            except MiniBatchProviderEmpty: # mbatch provider is empty
                break
            finally:
                map(lambda x:x.dealloc(), output)
                map(lambda x:x and x.dealloc(), indices)
                if teachbatch: teachbatch.dealloc()
                mbatch_provider.forgetOriginalData()

        if not self.cfg.finetune_online_learning:
            self.applyDeltaWeights(self.dWeights,self.dBias,updateOnlyLast, batchSize)
            map(lambda x: cp.fill(x,0),self.dWeights)
            map(lambda x: cp.fill(x,0),self.dBias)

        self.Errorrate.append((numberPictures - self.NumCorrect)/ float(numberPictures) )

        print "Train Correctly Classified: ", self.NumCorrect, "/", numberPictures
        print "Train Error-Rate:                 %2.3f"% (self.Errorrate[-1]*100)


  def runMLP(self, mbatch_provider, batchSize, epoch=0):

    self.NumCorrect = 0
    numberPictures  = 0
    teachbatch = None

    batch_idx = 0
    while True:
        try:
            #print "Batch ", batch+1, "/", numberBatches
            output, indices = [], []
            output.append(cp.dev_tensor_float_cm([self.cfg.px*self.cfg.py*self.cfg.maps_bottom,batchSize]))
            teachbatch = mbatch_provider.getMiniBatch(batchSize, output[0], return_teacher=True, id=batch_idx)
            numberPictures += teachbatch.shape[1]
            batch_idx += 1

            # Forward Pass
            for i in xrange(self.NumberOfLayers-1):
                linear = self.cfg.finetune_softmax and i==self.NumberOfLayers-2 # set output layer to linear
                output.append(self.forward(output[i], self.Weights[i], self.Bias[i],linear=linear))
            self.NumCorrect += self.getCorrect(output[-1], teachbatch)


        except MiniBatchProviderEmpty: # mbatch_provider empty
            break
        finally:
            map(lambda x:x.dealloc(), output)
            if teachbatch: teachbatch.dealloc()
            mbatch_provider.forgetOriginalData()


    self.testError.append((numberPictures - self.NumCorrect)/float(numberPictures)) 
    print "Test Correctly Classified:             ", self.NumCorrect, "/", numberPictures
    print "Test Error-Rate:                             %2.3f"% (100*self.testError[-1])

  def forward(self, input, weight, bias,linear=False):

    result = cp.dev_tensor_float_cm([weight.shape[1], input.shape[1]])
    cp.fill(result,0)
    cp.prod(result, weight, input, "t", "n")
    cp.matrix_plus_col(result, bias)
    if not linear: cp.apply_scalar_functor(result, cp.scalar_functor.SIGM)

    return result

  def applyDeltaWeights(self, dWList,dBList, updateOnlyLast, batchSize):
    if self.useRPROP:
        for i in reversed(xrange(self.NumberOfLayers-1)):
            cp.rprop(self.Weights[i], dWList[i], self.DeltaWeightsOld[i], self.WeightsLearnRate[i], self.cfg.finetune_cost)
            cp.rprop(self.Bias[i],    dBList[i],    self.DeltaBiasOld[i],    self.BiasLearnRate[i], self.cfg.finetune_cost)
            if updateOnlyLast: break
    else:
        for i in reversed(xrange(self.NumberOfLayers-1)):
            W, B   = self.Weights[i], self.Bias[i]
            dW,dWo = dWList[i], self.DeltaWeightsOld[i]
            dB,dBo = dBList[i], self.DeltaBiasOld[i]
            cp.apply_binary_functor(  dW, dWo, cp.binary_functor.XPBY, self.cfg.finetune_momentum)
            cp.apply_binary_functor(  dB, dBo, cp.binary_functor.XPBY, self.cfg.finetune_momentum)
            cp.learn_step_weight_decay(W, dW,    self.cfg.finetune_learnrate/batchSize, self.cfg.finetune_cost)
            cp.learn_step_weight_decay(B, dB,    self.cfg.finetune_learnrate/batchSize, self.cfg.finetune_cost)
            cp.copy(dWo,dW)
            cp.copy(dBo,dB)
            if updateOnlyLast: break

  def backward(self, output, teacher, indices, batchSize, updateOnlyLast, batch_idx):
    deltaWeights = []
    deltaBias = []
    derivative = []
    if self.cfg.finetune_softmax:
        derivative.append(self.delta_outputSoftMax(output[-1], teacher))
    else:
        derivative.append(self.delta_output(output[-1], teacher))

    for i in reversed(xrange(1,self.NumberOfLayers-1)):
        derivative.append(self.delta_hidden(self.Weights[i], derivative[-1], output[i]))
    derivative.reverse()

    #DeltaWeights                    
    for i in reversed(xrange(self.NumberOfLayers-1)):
        deltaWeights.append(self.calculateDeltaWeights(derivative[i], output[i],self.Weights[i]))
    deltaWeights.reverse()

    #DeltaBias                    
    for i in xrange(self.NumberOfLayers-1):
        self.createFilled(deltaBias, self.Bias[i].size, 1, 0)
        cp.reduce_to_col(deltaBias[-1], derivative[i])

    # Weight Update
    if self.cfg.finetune_online_learning and not self.useRPROP:
        self.applyDeltaWeights(deltaWeights,deltaBias,updateOnlyLast,batchSize)
    elif self.cfg.finetune_online_learning and self.useRPROP and batch_idx%16 == 0:
        self.applyDeltaWeights(self.dWeights,self.dBias,updateOnlyLast, batchSize)
        map(lambda x: cp.fill(x,0),self.dWeights)
        map(lambda x: cp.fill(x,0),self.dBias)
    else:
        for i in xrange(self.NumberOfLayers-1):
            cp.apply_binary_functor(self.dWeights[i], deltaWeights[i], cp.binary_functor.ADD)
            cp.apply_binary_functor(self.dBias[i], deltaBias[i], cp.binary_functor.ADD)

    da = lambda x:x.dealloc()
    map(da, deltaWeights)
    map(da, deltaBias)
    map(da, derivative)

  #calculating deltaWeights
  def calculateDeltaWeights(self, derivative, input,oldWeights):
      result = cp.dev_tensor_float_cm(oldWeights.shape)
      cp.prod(result, input,derivative, 'n', 't')
      return result

#calculating intermediary results for the Output-Layer
  def delta_output(self, calculated, correct):
    derivative = cp.dev_tensor_float_cm([calculated.shape[0], correct.shape[1]])
    h = cp.dev_tensor_float_cm(derivative.shape)
    cp.copy(derivative, calculated)
    cp.apply_scalar_functor(derivative, cp.scalar_functor.DSIGM)
    cp.copy(h, correct)
    cp.apply_binary_functor(h, calculated, cp.binary_functor.SUBTRACT)
    cp.apply_binary_functor(derivative, h, cp.binary_functor.MULT)
    h.dealloc()
    return derivative

  def delta_outputSoftMax(self, calculated, correct):
    derivative = calculated.copy()
    cp.apply_scalar_functor(derivative,  cp.scalar_functor.EXP)
    sums = cp.dev_tensor_float(calculated.shape[1])
    cp.fill(sums,0)
    cp.reduce_to_row(sums, derivative, cp.reduce_functor.ADD)
    cp.apply_scalar_functor(sums,cp.scalar_functor.ADD,0.1/derivative.shape[0])
    rv = cp.transposed_view(derivative)
    cp.matrix_divide_col(rv,sums)

    cp.apply_binary_functor(derivative,  correct,  cp.binary_functor.AXPBY, -1.,1.)
    sums.dealloc()

    return derivative

  #calculating intermediary results for a Hidden-Layer
  def delta_hidden(self, weight, knownDerivative, netInput):
    deltaLo = cp.dev_tensor_float_cm([weight.shape[0], netInput.shape[1]])

    cp.prod(deltaLo, weight, knownDerivative, 'n', 'n')
    help = netInput.copy()
    cp.apply_scalar_functor(help, cp.scalar_functor.DSIGM)
    cp.apply_binary_functor(deltaLo, help, cp.binary_functor.MULT)
    help.dealloc()

    return deltaLo

#calculating number of right results
  def getCorrect(self, calculated, correct):
    corr_idx = correct.np.argmax(axis=0)
    calc_idx = calculated.np.argmax(axis=0)
    return (corr_idx==calc_idx).sum()

  def saveLastLayer(self):
    np.save(os.path.join(self.cfg.workdir,"weights-%d-finetune"%(self.NumberOfLayers-1)),self.Weights[-1].np)
    np.save(os.path.join(self.cfg.workdir,"bias-%d-finetune"%(self.NumberOfLayers-1)),self.Bias[-1].np)
  def loadLastLayer(self,dim1,dim2):
    fn=os.path.join(self.cfg.workdir,"weights-%d-finetune.npy"%(self.NumberOfLayers-1))
    fn_bias=os.path.join(self.cfg.workdir,"bias-%d-finetune.npy"%(self.NumberOfLayers-1))
    if os.path.exists(fn) and os.path.exists(fn_bias):
        top_weights=np.load(fn)
        assert((dim1,dim2)==top_weights.shape)
        self.Weights.append(cp.push(top_weights))
        top_bias=np.load(fn_bias)
        assert(dim2==top_bias.shape[0])
        self.Bias.append(cp.push(top_bias))
        return 1
    else:
        return 0
