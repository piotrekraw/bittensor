#!/bin/python3
# The MIT License (MIT)
# Copyright © 2021 Yuma Rao

# Permission is hereby granted, free of charge, to any person obtaining a copy of this software and associated
# documentation files (the “Software”), to deal in the Software without restriction, including without limitation
# the rights to use, copy, modify, merge, publish, distribute, sublicense, and/or sell copies of the Software,
# and to permit persons to whom the Software is furnished to do so, subject to the following conditions:

# The above copyright notice and this permission notice shall be included in all copies or substantial portions of
# the Software.

# THE SOFTWARE IS PROVIDED “AS IS”, WITHOUT WARRANTY OF ANY KIND, EXPRESS OR IMPLIED, INCLUDING BUT NOT LIMITED TO
# THE WARRANTIES OF MERCHANTABILITY, FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL
# THE AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER LIABILITY, WHETHER IN AN ACTION
# OF CONTRACT, TORT OR OTHERWISE, ARISING FROM, OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER
# DEALINGS IN THE SOFTWARE.
""" The Exodus base client.

Example:
    $ python miners/text/template_client.py

"""
import bittensor
import sys
import time
import datetime
from threading import Lock
from datetime import datetime,timedelta
from loguru import logger; logger = logger.opt(colors=True)

import wandb
import pandas
import torch
import torch.nn.functional as F
from torch.nn.utils import clip_grad_norm_

def serve( 
        config, 
        model,
        subtensor = None,
        wallet = None,
        axon= None,
        metagraph = None,
    ):
    config.to_defaults()
    model= model.to(model.device)

    # Create Subtensor connection
    subtensor = bittensor.subtensor(config = config) if subtensor == None else subtensor

    # Load/Create our bittensor wallet.
    if wallet == None:
        wallet = bittensor.wallet( config = config ).create().register(subtensor=subtensor) 
    else:
        wallet.register(subtensor=subtensor)


    # Load/Sync/Save our metagraph.
    if metagraph == None:
        metagraph = bittensor.metagraph ( 
            subtensor = subtensor
        )
    
    metagraph.load().sync().save()

    # Create our optimizer.
    optimizer = torch.optim.SGD(
        [ {"params": model.parameters()} ],
        lr = config.neuron.learning_rate,
        momentum = config.neuron.momentum,
    )
    mutex = Lock()

    timecheck = {}
    n_topk_peer_weights = subtensor.min_allowed_weights

    def forward_generate( inputs_x:torch.FloatTensor, synapse, model_output = None):
        # output = model.pre_model.generate(
        #     input_ids=inputs_x, 
        #     max_length=synapse.num_to_generate, 
        #     num_beams=synapse.num_beams, 
        #     no_repeat_ngram_size=synapse.no_repeat_ngram_size,
        #     early_stopping = synapse.early_stopping,
        #     do_sample=synapse.do_sample, 
        #     top_p=synapse.top_p, 
        #     num_return_sequences=synapse.num_return_sequences,
        # )
        return None, torch.rand(inputs_x.shape[0], synapse.num_to_generate)

    def forward_hidden_state(inputs_x, synapse, model_output = None):
        # model_output, hidden = model.encode_forward(inputs_x.to(model.device), model_output = model_output)
        return None, torch.rand(inputs_x.shape[0], inputs_x.shape[1], bittensor.__network_dim__)

    def forward_casual_lm(inputs_x, synapse, model_output = None):
        # model_output, logits = model.encode_forward_causallm(inputs_x.to(model.device), model_output = model_output)
        q = torch.tensor([0.25, 0.5, 0.75])
        random = (-torch.normal(0, 4, size=(inputs_x.shape[0], inputs_x.shape[1], bittensor.__vocab_size__)).abs()*1.5)-3
        # print(logits.mean(), logits.std(), logits.flatten()[:1000].quantile(q))
        print(random.mean(), random.std(), random.flatten()[:1000].quantile(q))
        return None, random
    
    def optimizer_step():
        optimizer.step()
        optimizer.zero_grad()

    def blacklist(pubkey:str, request_type:bittensor.proto.RequestType) -> bool:
        r"""Axon security blacklisting, used to blacklist message from low stake members
            Args:
                pubkey ( str, `required`):
                    The public key of the caller.
                request_type ( bittensor.proto.RequestType, `required`):
                    the request type ('FORWARD' or 'BACKWARD').
        """
        # Check for registrations

        def registration_check():
            # If we allow non-registered requests return False = not blacklisted.
            is_registered = pubkey in metagraph.hotkeys
            if not is_registered:
                if config.neuron.blacklist_allow_non_registered:
                    
                    return False
                raise Exception('Registration blacklist')

        # Check for stake
        def stake_check() -> bool:
                
            # Check stake.
            uid = metagraph.hotkeys.index(pubkey)
            if metagraph.S[uid].item() < config.neuron.blacklist.stake:
                raise Exception('Stake blacklist')
            return False

        def validator_check():

            uid = metagraph.hotkeys.index(pubkey)
            if (metagraph.W[uid] >0).sum() >= n_topk_peer_weights:
                return False

            raise Exception('Validator blacklist')


        # Check for time
        def time_check():
            current_time = datetime.now()
            if pubkey in timecheck.keys():
                prev_time = timecheck[pubkey]
                if current_time - prev_time >= timedelta(seconds=config.neuron.blacklist.time):
                    timecheck[pubkey] = current_time
                    return False
                else:
                    timecheck[pubkey] = current_time
                    raise Exception('blacklist')
            else:
                timecheck[pubkey] = current_time
                return False

        # Black list or not
        #TODO: Turn on blacklist
        try:
            #registration_check()

            #stake_check()

            #validator_check()
            
            return False

        except Exception as e:
            return True
    
    def synapse_check(synapse, hotkey):
        """
        Custom synapse function to blacklist certain synapse functions depending on the stake
        """
        #TODO turn on synapse checking function
        if synapse.synapse_type == bittensor.proto.Synapse.SynapseType.TEXT_LAST_HIDDEN_STATE:
            pass
            
        elif synapse.synapse_type == bittensor.proto.Synapse.SynapseType.TEXT_CAUSAL_LM:
            pass
            
        elif synapse.synapse_type == bittensor.proto.Synapse.SynapseType.TEXT_SEQ_2_SEQ:
            pass
        
        return True

    def backward_callback(inputs_x:torch.FloatTensor, grads_dy:torch.FloatTensor, synapses=[] ):
        """
            The default backward callback when no callback is attached: Is used to call specific synapse functions

            Args:
                inputs_x (:obj:`torch.FloatTensor`, `required`): 
                    The inputs that will be passed to the synapse functions
                grads_dy (:obj:`torch.FloatTensor`, `required`):
                    The gradients that will be passed to the synapse functions
                synapses (:obj: list of bittensor.proto.SynapseArgs, 'Optional')
                    The proto message that contains additional args for individual synapse functions

            Returns:
                response_tensors: (:obj: list of bittensor.proto.Tensor, `required`): 
                    serialized tensor response from the nucleus call or None.
                response_codes: (:obj: list of bittensor.proto.ReturnCode, `required`)
                    return code associated with forward call i.e. Success of Timeout.
                response_messages: (:obj: list of strings, `required`)
                    return message associated with synapse call
        """
        # --- initialize response variables --- 
        response_tensors = []
        response_codes = []
        response_messages = []
        
        if not config.neuron.remote_train:
            return response_tensors, response_codes, response_messages

        # --- calling attached synapses ---
        with mutex and torch.enable_grad() and torch.autograd.set_detect_anomaly(True):
            for index, synapse in enumerate(synapses):
                try:
                    if synapse.synapse_type in axon.synapse_callbacks and axon.synapse_callbacks[synapse.synapse_type] != None:
                        model_output, response_tensor = axon.synapse_callbacks[synapse.synapse_type](inputs_x[index], synapse)
                        grads_dy_norm = grads_dy[index]/(grads_dy[index].sum() + 0.00001)
                        torch.autograd.backward (
                            tensors = [ response_tensor ],
                            grad_tensors = [ grads_dy_norm ],
                            retain_graph=True
                        )                        
                        model.backward_gradients_count += inputs_x[index].size(0)
                        response_tensors.append(None)
                        response_codes.append(bittensor.proto.ReturnCode.Success)
                        response_messages.append('Success')
                    else:
                        response_tensors.append(None)
                        response_codes.append(bittensor.proto.ReturnCode.NotImplemented)
                        response_messages.append('Not Implemented')
                except Exception as e:
                    # --- Exception Hit in Synapse ---
                    response_tensors.append(None)
                    response_codes.append(bittensor.proto.ReturnCode.UnknownException)
                    response_messages.append(str(e))

        return response_tensors, response_codes, response_messages

    # Create our axon server and subscribe it to the network.
    if axon == None:
        axon = bittensor.axon(
            config = config,
            wallet = wallet,
            synapse_last_hidden = forward_hidden_state if model.config.neuron.lasthidden else None,
            synapse_causal_lm = forward_casual_lm if model.config.neuron.causallm else None,
            synapse_seq_2_seq = forward_generate if model.config.neuron.seq2seq else None ,
            blacklist = blacklist,
        ).start().serve(subtensor=subtensor)
    
    axon.optimizer_step = optimizer_step
    axon.attach_backward_callback(backward_callback)
    # Training Data
    if config.neuron.local_train:
        dataset = bittensor.dataset(config=config)
        dataset.set_data_size(10, 64)
        data = next(dataset)

    # load our old model
    if not config.neuron.restart :
        model.load(config.neuron.full_path)

    if config.wandb.api_key != 'default':
        # --- Init Wandb.
        bittensor.wandb(
            config = config,
            cold_pubkey = wallet.coldkeypub.ss58_address,
            hot_pubkey = wallet.hotkey.ss58_address,
            root_dir = config.neuron.full_path
        )

    last_set_block = subtensor.get_current_block()


    # --- Run Forever.
    while True:
        
        iteration = 0
        local_data = {}
        nn = subtensor.neuron_for_pubkey(wallet.hotkey.ss58_address)
        uid = metagraph.hotkeys.index( wallet.hotkey.ss58_address )
        current_block = subtensor.get_current_block()
        end_block = current_block + config.neuron.blocks_per_epoch
        if config.neuron.local_train:
            # --- Training step.
            while end_block >= current_block:
                if current_block != subtensor.get_current_block():
                    loss, _ = model( next( dataset ).to(model.device) )
                    if iteration > 0 : 
                        losses += loss
                    else:
                        losses = loss
                    iteration += 1
                    current_block = subtensor.get_current_block()
                    logger.info(f'local training\titeration: {iteration}\tloss: {loss}')
            
            if iteration != 0:
                (losses/iteration).backward()
        
        else:
            while end_block >= current_block:
                time.sleep(12)
                current_block = subtensor.get_current_block()


        # --- Update parameters
        if (config.neuron.local_train and iteration > 0) or (config.neuron.remote_train and model.backward_gradients_count > 0):
            # Custom learning rate
            if model.backward_gradients_count > 0:
                optimizer.param_groups[0]['lr'] =  0.1/(model.backward_gradients_count)
            else:
                optimizer.param_groups[0]['lr'] =  0.1

            logger.info('Backpropagation Started')
            clip_grad_norm_(model.parameters(), 1.0)
            optimizer.step()
            optimizer.zero_grad()
            model.backward_gradients = 0
            logger.info('Backpropagation Successful: Model updated')
            local_data = {'local/loss': losses.detach().item() / iteration}

            if local_data['local/loss'] < model.best_loss:
                model.best_loss = local_data['local/loss']
                model.save(config.neuron.full_path)

        wandb_data = {            
            'stake': nn.stake,
            'rank': nn.rank,
            'trust': nn.trust,
            'consensus': nn.consensus,
            'incentive': nn.incentive,
            'emission': nn.emission,
        }
        
        if config.wandb.api_key != 'default':

            df = pandas.concat( [
                bittensor.utils.indexed_values_to_dataframe( prefix = 'w_i_{}'.format(nn.uid), index = metagraph.uids, values = metagraph.W[:, uid] ),
                axon.to_dataframe( metagraph = metagraph ),
            ], axis = 1)
            df['uid'] = df.index
            wandb_info_axon = axon.to_wandb()                
            wandb.log( { **wandb_data, **wandb_info_axon, **local_data }, step = current_block )
            wandb.log( { 'stats': wandb.Table( dataframe = df ) }, step = current_block )

        if current_block - last_set_block > config.neuron.blocks_per_set_weights:
            try: 
                bittensor.__console__.print('[green]Current Status:[/green]', {**wandb_data, **local_data})

                last_set_block = current_block
                # Set self weights to maintain activity.
                # --- query the chain for the most current number of peers on the network
                chain_weights = torch.zeros(subtensor.n)
                chain_weights [ uid ] = 1 
                did_set = subtensor.set_weights(
                    uids=torch.arange(0,subtensor.n),
                    weights = chain_weights,
                    wait_for_inclusion = False,
                    wallet = wallet,
                )
                
                metagraph.sync()
                if did_set:
                    logger.success('Successfully set weights on the chain')
                else:
                    logger.error('Failed to set weights on chain. (Timeout)')
            except Exception as e:
                logger.error('Failure setting weights on chain with error: {}', e)