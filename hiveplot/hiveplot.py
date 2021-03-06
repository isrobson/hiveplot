import numpy as np
import matplotlib.pyplot as plt
import matplotlib.patches as patches

from matplotlib.path import Path


class HivePlot(object):
    """
    The HivePlot class will take in the following and return
    a hive plot:
    - nodes:    a dictionary of nodes, in which there are at most 3 keys
                in the dictionary, and the nodes are sorted in a
                pre-specified order. One common grouping is by a node
                attribute and one possible ordering is by degree centrality.

    - edges:    a dictionary of {group:edgelist}, where each edgelist is a
                list of (u,v,d) tuples (in NetworkX style), where u and v are
                the nodes to join, and d are the node attributes.

    The user will have to pre-sort and pre-group the nodes, and pre-map
    the edge color groupings. This code will determine the positioning
    and exact drawing of the edges.

    Hive plots are non-trivial to construct. These are the most important
    features one has to consider:
    -    Grouping of nodes:
        -    at most 3 groups.
    -    Ordering of nodes:
        -    must have an ordinal or continuous node attribute
    -    Cross-group edges:
        -    Undirected is easier to draw than directed.
        -    Directed is possible.
    -    Within-group edges:
        -    Requires the duplication of an axis.
    """

    def __init__(self, nodes, edges, node_colormap, edge_colormap=None,
                 linewidth=0.5, is_directed=False, scale=10, ax=None,
                 fig=None, group_scale=None, reverse_to_expand=None, skip_within=False,
                 axis_pad=None):
        super(HivePlot, self).__init__()
        self.nodes = nodes  # dictionary of {group:[ordered_nodes] list}
        self.edges = edges  # dictionary of {group:[(u,v,d)] tuples list}

        # boolean of whether graph is supposed to be directed or not
        self.is_directed = is_directed
        if fig is None:
            self.fig = plt.figure(figsize=(8, 8))
        else:
            self.fig = fig
        if ax is None:
            self.ax = self.fig.add_subplot(111)
        else:
            self.ax = ax
        self.scale = scale
        self.dot_radius = self.scale / float(4)
        self.internal_radius = scale ** 2
        self.linewidth = linewidth
        self.node_colormap = node_colormap  # dictionary of node_group:color
        self.edge_colormap = edge_colormap  # dictionary of edge_group:color

        self.major_angle = 0
        self.initialize_major_angle()
        self.minor_angle = 0
        self.initialize_minor_angle()
        
        # sets a scaling for each group
        if group_scale:
            self.group_scale = group_scale
        else:
            self.group_scale = {group:1.0 for group in self.nodes.keys()}
            
            
        # dictionary of group:True/False
        # at least one must be False
        if reverse_to_expand:
            assert(all(list(reverse_to_expand.values())) == False)
            self.reverse_to_expand = reverse_to_expand
        else:
            self.reverse_to_expand = {group:False for group in self.nodes.keys()}
            
        # manually override checking for within group edges
        self.skip_within = skip_within
            
        # initialize plot radius caches
        self.radius_cache = None    
        self.node_radius_cache = {}
        self.node_group_membership_cache = {}
        
        if axis_pad:
            self.axis_pad = axis_pad
        else:
            self.axis_pad = 0

    """
    Steps in graph drawing:
    1.  Determine the number of groups. This in turn determines the number of
        axes to draw, and the major angle between the axes.

    2.  For each group, determine whether there are edges between members of
        the same group.
        a.  If True:
            -   Duplicate the axis by shifting off by a minor angle.
            -   Draw each axis line, with length proportional to number of
                nodes in the group:
                -    One is at major angle + minor angle
                -    One is at major angle - minor angle
            -   Draw in the nodes.
        b.  If False:
            -   Draw the axis line at the major angle.
            -   Length of axis line is proportional to the number of nodes in
                the group
            -   Draw in the nodes.

    3.  Determine which node group is at the 0 radians position. The angles
        that are calculated will have to be adjusted for whether it is at 2*pi
        radians or at 0 radians, depending on the angle differences.

    4.  For each edge, determine the radial position of the start node and end
        node. Compute the middle angle and the mean radius of the start and
        end nodes.
    """

    def simplified_edges(self):
        """
        A generator for getting all of the edges without consuming extra
        memory.
        """
        for group, edgelist in self.edges.items():
            for u, v, d in edgelist:
                yield (u, v)

    def initialize_major_angle(self):
        """
        Computes the major angle: 2pi radians / number of groups.
        """
        num_groups = len(self.nodes.keys())
        self.major_angle = 2 * np.pi / num_groups

    def initialize_minor_angle(self):
        """
        Computes the minor angle: 2pi radians / 3 * number of groups.
        """
        num_groups = len(self.nodes.keys())

        self.minor_angle = 2 * np.pi / (6 * num_groups)

    def set_minor_angle(self, angle):
        """
        Sets the major angle of the hive plot. I have restricted this to be
        less than the major angle.
        """
        assert angle < self.major_angle,\
            "Minor angle cannot be greater than the major angle."

        self.minor_angle = angle

    def plot_radius(self):
        """
        Computes the plot radius: maximum of length of each list of nodes.
        """
        if self.radius_cache:
            return self.radius_cache
        else:
            plot_rad = 0
            for group, nodelist in self.nodes.items():
                # add group scale 
                proposed_radius = len(nodelist) * self.scale * self.group_scale[group]
                if proposed_radius > plot_rad:
                    plot_rad = proposed_radius
                    
            self.radius_cache = plot_rad + self.internal_radius
            return self.radius_cache

    def axis_length(self, group):
        """
        Computes the length of the axis for a given group.
        """
        return len(self.nodes[group])

    def has_edge_within_group(self, group):
        """
        Checks whether there are within-group edges or not.
        """
        if self.skip_within:
            return False 
        else:
            assert group in self.nodes.keys(),\
                "{0} not one of the group of nodes".format(group)
            nodelist = self.nodes[group]
            for n1, n2 in self.simplified_edges():
                if n1 in nodelist and n2 in nodelist:
                    return True

    def plot_axis(self, rs, theta):
        """
        Renders the axis.
        """
        xs, ys = get_cartesian(rs, theta)
        self.ax.plot(xs, ys, 'black', alpha=0.3)

    def plot_nodes(self, nodelist, theta, group):
        """
        Plots nodes to screen.
        """
        for i, node in enumerate(nodelist):
            # add in the group scale
            node_group = self.find_node_group_membership(node)
            
            g_scale = self.group_scale[node_group]
            
            if self.reverse_to_expand[node_group]:
                r = self.plot_radius() - i * self.scale * g_scale
            else:
                r = self.internal_radius + i * self.scale * g_scale
            x, y = get_cartesian(r, theta)
            circle = plt.Circle(xy=(x, y), radius=self.dot_radius*g_scale,
                                color=self.color_node(node), linewidth=0)
            self.ax.add_patch(circle)

    def group_theta(self, group):
        """
        Computes the theta along which a group's nodes are aligned.
        """
        for i, g in enumerate(self.nodes.keys()):
            if g == group:
                return i * self.major_angle

    def add_axes_and_nodes(self):
        """
        Adds the axes (i.e. 2 or 3 axes, not to be confused with matplotlib
        axes) and the nodes that belong to each axis.
        """
        for i, (group, nodelist) in enumerate(self.nodes.items()):
            theta = self.group_theta(group)

            if self.has_edge_within_group(group):
                    theta = theta - self.minor_angle
                    self.plot_nodes(nodelist, theta, group)

                    theta = theta + 2 * self.minor_angle
                    self.plot_nodes(nodelist, theta, group)

            else:
                self.plot_nodes(nodelist, theta, group)

    def find_node_group_membership(self, node):
        """
        Identifies the group for which a node belongs to.
        """
        if self.node_group_membership_cache.get(node):
            return self.node_group_membership_cache.get(node)
        else:
            for group, nodelist in self.nodes.items():
                if node in nodelist:
                    self.node_group_membership_cache.update({node:group})
                    return group

    def get_idx(self, node):
        """
        Finds the index of the node in the sorted list.
        """
        group = self.find_node_group_membership(node)
        return self.nodes[group].index(node)

    def node_radius(self, node):
        """
        Computes the radial position of the node.
        """
        #print(node)
        # add g_scale
        if self.node_radius_cache.get(node):
            return self.node_radius_cache.get(node)
        else:
            node_group = self.find_node_group_membership(node)
            g_scale = self.group_scale[node_group]

            if self.reverse_to_expand[node_group]:
                self.node_radius_cache.update({node:self.plot_radius() - self.get_idx(node) * self.scale * g_scale})
                return self.node_radius_cache.get(node)
            else:
                self.node_radius_cache.update({node:self.get_idx(node) * self.scale * g_scale + self.internal_radius})
                return self.node_radius_cache.get(node)

    def node_theta(self, node):
        """
        Convenience function to find the node's theta angle.
        """
        group = self.find_node_group_membership(node)
        return self.group_theta(group)

    def draw_edge(self, n1, n2, d, group):
        """
        Renders the given edge (n1, n2) to the plot.
        """
        start_radius = self.node_radius(n1)
        start_theta = self.node_theta(n1)

        end_radius = self.node_radius(n2)
        end_theta = self.node_theta(n2)

        start_theta, end_theta = self.correct_angles(start_theta, end_theta)
        start_theta, end_theta = self.adjust_angles(n1, start_theta, n2,
                                                    end_theta)

        middle1_radius = np.min([start_radius, end_radius])
        middle2_radius = np.max([start_radius, end_radius])

        if start_radius > end_radius:
            middle1_radius, middle2_radius = middle2_radius, middle1_radius

        middle1_theta = np.mean([start_theta, end_theta])
        middle2_theta = np.mean([start_theta, end_theta])

        startx, starty = get_cartesian(start_radius, start_theta)
        middle1x, middle1y = get_cartesian(middle1_radius, middle1_theta)
        middle2x, middle2y = get_cartesian(middle2_radius, middle2_theta)
        # middlex, middley = get_cartesian(middle_radius, middle_theta)
        endx, endy = get_cartesian(end_radius, end_theta)

        verts = [(startx, starty),
                 (middle1x, middle1y),
                 (middle2x, middle2y),
                 (endx, endy)]
        codes = [Path.MOVETO, Path.CURVE4, Path.CURVE4, Path.CURVE4]

        path = Path(verts, codes)
        if self.edge_colormap is None:
            edgecolor = 'black'
        else:
            edgecolor = self.color_edge((n1,n2,d), group)
        patch = patches.PathPatch(path, lw=self.linewidth, facecolor='none',
                                  edgecolor=edgecolor, alpha=0.3)
        self.ax.add_patch(patch)

    def add_edges(self):
        """
        Draws all of the edges in the graph.
        """
        for group, edgelist in self.edges.items():
            for (u, v, d) in edgelist:
                self.draw_edge(u, v, d, group)

    def draw(self):
        """
        The master function that is called that draws everything.
        """
        self.ax.set_xlim(-self.plot_radius()-self.axis_pad, self.plot_radius()+self.axis_pad)
        self.ax.set_ylim(-self.plot_radius()-self.axis_pad, self.plot_radius()+self.axis_pad)

        self.add_axes_and_nodes()
        self.add_edges()

        self.ax.axis('off')

    def adjust_angles(self, start_node, start_angle, end_node, end_angle):
        """
        This function adjusts the start and end angles to correct for
        duplicated axes.
        """
        start_group = self.find_node_group_membership(start_node)
        end_group = self.find_node_group_membership(end_node)

        if start_group == 0 and end_group == len(self.nodes.keys())-1:
            if self.has_edge_within_group(start_group):
                start_angle = correct_negative_angle(start_angle -
                                                     self.minor_angle)
            if self.has_edge_within_group(end_group):
                end_angle = correct_negative_angle(end_angle +
                                                   self.minor_angle)

        elif start_group == len(self.nodes.keys())-1 and end_group == 0:
            if self.has_edge_within_group(start_group):
                start_angle = correct_negative_angle(start_angle +
                                                     self.minor_angle)
            if self.has_edge_within_group(end_group):
                end_angle = correct_negative_angle(end_angle -
                                                   self.minor_angle)

        elif start_group < end_group:
            if self.has_edge_within_group(end_group):
                end_angle = correct_negative_angle(end_angle -
                                                   self.minor_angle)
            if self.has_edge_within_group(start_group):
                start_angle = correct_negative_angle(start_angle +
                                                     self.minor_angle)

        elif end_group < start_group:
            if self.has_edge_within_group(start_group):
                start_angle = correct_negative_angle(start_angle -
                                                     self.minor_angle)
            if self.has_edge_within_group(end_group):
                end_angle = correct_negative_angle(end_angle +
                                                   self.minor_angle)

        return start_angle, end_angle

    def correct_angles(self, start_angle, end_angle):
        """
        This function corrects for the following problems in the edges:
        """
        # Edges going the anti-clockwise direction involves angle = 0.
        if start_angle == 0 and (end_angle - start_angle > np.pi):
            start_angle = np.pi * 2
        if end_angle == 0 and (end_angle - start_angle < -np.pi):
            end_angle = np.pi * 2

        # Case when start_angle == end_angle:
        if start_angle == end_angle:
            start_angle = start_angle - self.minor_angle
            end_angle = end_angle + self.minor_angle

        return start_angle, end_angle
    
    def color_node(self, node):
        """
        This function enables easy coloring with simple colors as well as colormap functions
        """
        node_group = self.find_node_group_membership(node)
        node_cmap = self.node_colormap[node_group]
        #print(node)
        
        if isinstance(node_cmap, str):
            return node_cmap
        else:
            # assume function of some kind
            return node_cmap(node)
        
    def color_edge(self, edge, group):
        """
        This function enables easy coloring with simple colors as well as colormap functions
        """
        edge_cmap = self.edge_colormap[group]
        
        if isinstance(edge_cmap, str):
            return edge_cmap
        else:
            # assume function of some kind
            return edge_cmap(edge)
        


"""
Global helper functions go here.
"""


def get_cartesian(r, theta):
    """
    Given a radius and theta, return the cartesian (x, y) coordinates.
    """
    x = r*np.sin(theta)
    y = r*np.cos(theta)

    return x, y


def correct_negative_angle(angle):
    """
    Corrects a negative angle to a positive one.
    """
    if angle < 0:
        angle = 2 * np.pi + angle
    else:
        pass

    return angle
