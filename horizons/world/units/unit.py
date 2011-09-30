# ###################################################
# Copyright (C) 2011 The Unknown Horizons Team
# team@unknown-horizons.org
# This file is part of Unknown Horizons.
#
# Unknown Horizons is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 2 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program; if not, write to the
# Free Software Foundation, Inc.,
# 51 Franklin St, Fifth Floor, Boston, MA  02110-1301  USA
# ###################################################

import math
import logging
from fife import fife

import horizons.main

from horizons.world.units.movingobject import MovingObject
from horizons.util import Point, WorldObject, WeakMethod, Circle, decorators
from horizons.constants import LAYERS
from horizons.world.component.ambientsoundcomponent import AmbientSoundComponent
from horizons.world.component.healthcomponent import HealthComponent
from horizons.world.component.storagecomponent import StorageComponent

class Unit(MovingObject):
	log = logging.getLogger("world.units")
	is_unit = True
	is_ship = False
	health_bar_y = -30
	is_selectable = False

	def __init__(self, x, y, owner=None, **kwargs):
		super(Unit, self).__init__(x=x, y=y, **kwargs)
		self.__init(x, y, owner)

	def __init(self, x, y, owner):
		self.owner = owner
		class Tmp(fife.InstanceActionListener): pass
		self.InstanceActionListener = Tmp()
		self.InstanceActionListener.onInstanceActionFinished = \
				WeakMethod(self.onInstanceActionFinished)
		self.InstanceActionListener.thisown = 0 # fife will claim ownership of this
		if self._object is None:
			self.__class__._loadObject()

		self._instance = self.session.view.layers[LAYERS.OBJECTS].createInstance( \
			self._object, fife.ModelCoordinate(int(x), int(y), 0), str(self.worldid))
		fife.InstanceVisual.create(self._instance)
		location = fife.Location(self._instance.getLocation().getLayer())
		location.setExactLayerCoordinates(fife.ExactModelCoordinate(x + x, y + y, 0))
		self.act(self._action, location, True)
		self._instance.addActionListener(self.InstanceActionListener)

		self.loading_area = self.position
		self.add_component(AmbientSoundComponent)

	def remove(self):
		self.log.debug("Unit.remove for %s started", self)
		if hasattr(self.owner, 'remove_unit'):
			self.owner.remove_unit(self)
		self._instance.removeActionListener(self.InstanceActionListener)
		super(Unit, self).remove()

	def onInstanceActionFinished(self, instance, action):
		"""
		@param instance: fife.Instance
		@param action: string representing the action that is finished.
		"""
		location = fife.Location(self._instance.getLocation().getLayer())
		location.setExactLayerCoordinates(fife.ExactModelCoordinate( \
			self.position.x + self.position.x - self.last_position.x, \
			self.position.y + self.position.y - self.last_position.y, 0))
		if action.getId() != ('move_'+self._action_set_id):
			self.act(self._action, self._instance.getFacingLocation(), True)
		else:
			self.act(self._action, location, True)
		self.session.view.cam.refresh()

	def draw_health(self):
		"""Draws the units current health as a healthbar over the unit."""
		if not self.has_component(HealthComponent):
			return
		health_component = self.get_component(HealthComponent)
		health = health_component.health
		max_health = health_component.max_health
		renderer = self.session.view.renderer['GenericRenderer']
		renderer.removeAll("health_" + str(self.worldid))
		zoom = self.session.view.get_zoom()
		height = int(5 * zoom)
		width = int(50 * zoom)
		y_pos = int(self.health_bar_y * zoom)
		mid_node_up = fife.GenericRendererNode(self._instance, \
									fife.Point(-width/2+int(((health/max_health)*width)),\
		                                       y_pos-height)
		                            )
		mid_node_down = fife.GenericRendererNode(self._instance, \
		                                         fife.Point(
		                                             -width/2+int(((health/max_health)*width))
		                                             ,y_pos)
		                                         )
		if health != 0:
			renderer.addQuad("health_" + str(self.worldid), \
			                fife.GenericRendererNode(self._instance, \
			                                         fife.Point(-width/2, y_pos-height)), \
			                mid_node_up, \
			                mid_node_down, \
			                fife.GenericRendererNode(self._instance, fife.Point(-width/2, y_pos)), \
			                0, 255, 0)
		if health != max_health:
			renderer.addQuad("health_" + str(self.worldid), mid_node_up, \
			                 fife.GenericRendererNode(self._instance, fife.Point(width/2, y_pos-height)), \
			                 fife.GenericRendererNode(self._instance, fife.Point(width/2, y_pos)), \
			                 mid_node_down, 255, 0, 0)

	def hide(self):
		"""Hides the unit."""
		vis = self._instance.get2dGfxVisual()
		vis.setVisible(False)

	def show(self):
		vis = self._instance.get2dGfxVisual()
		vis.setVisible(True)

	def save(self, db):
		super(Unit, self).save(db)

		owner_id = 0 if self.owner is None else self.owner.worldid
		db("INSERT INTO unit (rowid, type, x, y, owner) VALUES(?, ?, ?, ?, ?)",
			self.worldid, self.__class__.id, self.position.x, self.position.y, \
					owner_id)

	def load(self, db, worldid):
		super(Unit, self).load(db, worldid)

		x, y, owner_id = db("SELECT x, y, owner FROM unit WHERE rowid = ?", worldid)[0]
		if (owner_id == 0):
			owner = None
		else:
			owner = WorldObject.get_object_by_id(owner_id)
		self.__init(x, y, owner)

		return self

	def transfer_to_storageholder(self, amount, res_id, transfer_to):
		"""Transfers amount of res_id to transfer_to.
		@param transfer_to: worldid or object reference
		@return: amount that was actually transfered (NOTE: this is different from the
						 return value of inventory.alter, since here are 2 storages involved)
		"""
		try:
			transfer_to = WorldObject.get_object_by_id( int(transfer_to) )
		except TypeError: # transfer_to not an int, assume already obj
			pass
		# take res from self
		ret = self.get_component(StorageComponent).inventory.alter(res_id, -amount)
		# check if we were able to get the planed amount
		ret = amount if amount < abs(ret) else abs(ret)
		# put res to transfer_to
		ret = transfer_to.get_component(StorageComponent).inventory.alter(res_id, amount-ret)
		self.get_component(StorageComponent).inventory.alter(res_id, ret) # return resources that did not fit
		return amount-ret

	def get_random_location(self, in_range):
		"""Returns a random location in walking_range, that we can find a path to
		Does not check every point, only a few samples are tried.
		@param in_range: int, max distance to returned point from current position
		@return: tuple(Instance of Point or None, path or None)"""
		range_squared = in_range * in_range
		randint = self.session.random.randint
		# pick a sample, try tries times
		tries = int(range_squared / 2)
		for i in xrange(tries):
			# choose x-difference, then y-difference so that the distance is in the range.
			x_diff = randint(1, in_range) # always go at least 1 field
			y_max_diff = int( math.sqrt(range_squared - x_diff*x_diff) )
			y_diff = randint(0, y_max_diff)
			# use randomness of x/y_diff below, randint calls are expensive
			# this results in a higher chance for x > y than y < x, so equalize
			if (x_diff + y_diff) % 2 == 0:
				x_diff, y_diff = y_diff, x_diff
			# direction
			if x_diff % 2 == 0:
				y_diff = -y_diff
			if y_diff % 2 == 0:
				x_diff = -x_diff
			# check this target
			possible_target = Point(self.position.x + x_diff, self.position.y + y_diff)
			path = self.check_move(possible_target)
			if path:
				return (possible_target, path)
		return (None, None)

	@property
	def classname(self):
		return horizons.main.db.cached_query("SELECT name FROM unit where id = ?", self.id)[0][0]

	def __str__(self): # debug
		return '%s(id=%s;worldid=%s)' % (self.classname, self.id, self.worldid)


decorators.bind_all(Unit)
